"""
orchestrator/weekly_job.py
--------------------------
Job principal para la ejecución semanal (MVP).
Genera diversidad de contenidos excluyendo chunks previamente usados temporalmente.
"""
import logging
from typing import List, Dict, Any, Optional

from orchestrator.base import JobType
from poc.agents.registry import get_agent, list_formats
from storage.notion_client import NotionClient
from agent.tools import hybrid_search, mark_chunk_used
from ingestion.embedder import get_embedder

logger = logging.getLogger(__name__)

class WeeklyContentJob(JobType):
    """
    Se encarga de orquestar la generación de piezas dictadas por una lista de requerimientos (Rules),
    asegurando diversidad temporal y ejecutando a los subagentes correctos.
    """
    def __init__(self, org_id: str = "default", dry_run: bool = False):
        self.org_id = org_id
        self.dry_run = dry_run
        self.notion_client = NotionClient(organization_id=org_id)
        
        # Mantiene un registro de chunks seleccionados en este mismo run para evitar repetirlos internamente
        self._local_used_chunks = set()

    async def get_requirements(self) -> List[Dict[str, Any]]:
        """
        Obtiene las reglas (qué formatos generar y cantidad) desde Notion.
        Si falla o retorna vacío, usa el DEFAULT fall-back internamente o lo delega al llamador.
        """
        rules = await self.notion_client.get_weekly_rules()
        return rules

    def get_subagents(self) -> List[str]:
        """
        Retorna la lista de formatos disponibles expuestos por los agentes actuales.
        """
        return list_formats()

    async def run_rule(self, rule: Dict[str, Any], run_id: str) -> Dict[str, Any]:
        """
        Ejecuta la generación para una regla.
        Retorna un dict con:
          - pieces: List[dict]  — piezas que pasaron QA
          - failed_count: int   — piezas que fallaron QA o tuvieron error
          - total_cost: float   — costo total acumulado del run_rule
        """
        formato = rule.get("formato")
        topic = rule.get("topico", "")
        qty = rule.get("cantidad", 1)

        if formato not in self.get_subagents():
            logger.error(f"WeeklyContentJob: Formato no soportado '{formato}' en regla.")
            return {"pieces": [], "failed_count": 0, "total_cost": 0.0}

        agent = get_agent(formato)
        intents = self.generate_search_intents(topic)
        
        pieces_generated = []
        pieces_failed_count = 0
        total_cost_run = 0.0
        
        from poc.agents.base_agent import AgentInput
        
        for i in range(qty):
            # Rotar intents para diversidad inicial si la cantidad es mayor a intents predecibles
            current_intent = intents[i % len(intents)]
            
            # Buscar contexto en la DB
            chunk = await self._find_best_chunk(current_intent)
            
            # Generar
            logger.info(f"Generando {formato} [{i+1}/{qty}] con intent: '{current_intent}'")
            try:
                # El agent.generate abstrae la llamada LLM, parseo y validaciones
                agent_input = AgentInput(
                    topic=current_intent,
                    chunk=chunk,
                    sop=await self.notion_client.get_sop(formato),
                    extra={"tipo": "Generacion Automatica"},
                )
                result = await agent.generate(agent_input)
                
                total_cost_run += result.cost_usd
                
                # Si pasa validaciones, loggeamos como completado
                if result.qa_passed:
                    piece_data = {
                        **result.content,
                        "chunk_id": chunk.get("chunk_id") if chunk else None,
                        "run_id": run_id,
                        "cost_usd": result.cost_usd,
                    }
                    pieces_generated.append(piece_data)
                    
                    # Marcar Chunk DB Level + Local Level
                    if chunk and chunk.get("chunk_id"):
                        self._local_used_chunks.add(chunk["chunk_id"])
                        if not self.dry_run:
                            await mark_chunk_used(chunk["chunk_id"])
                            
                    # Publicar en Notion
                    if not self.dry_run:
                        page_id = await self.notion_client.publish_piece(formato, piece_data)
                        if page_id:
                            logger.info(f"Pieza {formato} publicada. ID: {page_id}")
                else:
                    pieces_failed_count += 1
                    logger.warning(f"Pieza {formato} falló QA: {result.qa_reason}")

            except Exception as e:
                logger.error(f"Error procesando generación de {formato}: {e}", exc_info=True)
                pieces_failed_count += 1
                # Permite que las excepciones reboten internamente pero no frenen todo el loop

        return {
            "pieces": pieces_generated,
            "failed_count": pieces_failed_count,
            "total_cost": total_cost_run,
        }

    async def _find_best_chunk(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Busca el mejor chunk disponible para un intent dado, excluyendo temporalmente.
        """
        try:
            embedder = get_embedder()
            query_embedding, _ = await embedder.generate_embedding(query)
            results = await hybrid_search(
                query=query,
                query_embedding=query_embedding,
                limit=5,
                diversity_lookback_days=30
            )
            
            for res in results:
                cid = res.chunk_id
                if cid not in self._local_used_chunks:
                    # Parse internal object to dict expected by Agents
                    return {
                        "chunk_id": cid,
                        "document_id": res.document_id,
                        "content": res.content,
                        "metadata": res.metadata,
                    }
                    
            # Si todos los del top 5 locales ya fueron usados en el mismo intento, retorna None u o el primero menos relevante
            return None
        except Exception as e:
            logger.error(f"_find_best_chunk falló para query '{query}': {e}")
            return None
