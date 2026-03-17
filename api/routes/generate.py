"""
api/routes/generate.py
----------------------
POST /generate/weekly — Dispara la generación semanal completa.

Llamado por n8n cada domingo a las 23:00.
También puede llamarse manualmente para testing.

Flujo completo:
    1. Lee Weekly Rules de Notion (o usa formats_override si se pasa)
    2. Para cada regla {formato, topico, cantidad}:
       a. Search Intent Generator: expande el tópico en múltiples ángulos
       b. Para cada ángulo: hybrid_search_with_entities() → chunk más relevante y diverso
       c. Para cada chunk: agente.generate() → pieza JSON estructurada
       d. QA Gate programático
       e. Si pasa: publish_piece() en Notion
       f. mark_chunk_used() siempre
    3. Guarda WeeklyRun en Postgres
    4. Notifica por Telegram con resumen

NOTA: Este endpoint puede tardar varios minutos en completarse.
Para runs de producción, considerar una arquitectura de background jobs
con polling de estado (fuera del scope del MVP).
"""
import asyncio
import logging
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from api.models.generate import GenerateRequest, GenerateResponse
from poc.config import config
from poc.budget_guard import check_budget_and_warn, get_active_model, record_cost
from agent.db_utils import DatabasePool, get_db_connection
from ingestion.embedder import get_embedder

logger = logging.getLogger(__name__)
router = APIRouter()


# =============================================================================
# CONFIGURACIÓN HARDCODEADA PARA CUANDO NO HAY NOTION (Fase 1 MVP mínimo)
# En producción, esto se lee de Notion Weekly Rules.
# =============================================================================

DEFAULT_WEEKLY_RULES = [
    {"formato": "reel_cta",          "topico": "objeciones de precio en ventas B2B", "cantidad": 3},
    {"formato": "reel_cta",          "topico": "validación de ideas de negocio",     "cantidad": 2},
    {"formato": "historia",          "topico": "liderazgo y emprendimiento",         "cantidad": 2},
    {"formato": "email",             "topico": "ventas B2B y cierre de deals",       "cantidad": 2},
    {"formato": "reel_lead_magnet",  "topico": "miedos del emprendedor",             "cantidad": 1},
]


@router.post("/generate/weekly", response_model=GenerateResponse, tags=["Generación"])
async def generate_weekly(request: GenerateRequest) -> GenerateResponse:
    """
    Dispara la generación semanal de contenido.

    Lee las reglas de Notion (o usa defaults), busca chunks relevantes
    y genera piezas para cada formato configurado.

    En modo `dry_run=true`, simula el proceso sin llamar al LLM ni publicar en Notion.
    Útil para verificar la configuración antes del primer run real.
    """
    run_id = str(uuid.uuid4())

    logger.info(
        "POST /generate/weekly: run_id=%s org='%s' dry_run=%s",
        run_id, request.organization_id, request.dry_run
    )

    # ── Verificar presupuesto antes de empezar ────────────────────────────────
    if not request.dry_run:
        budget_status = check_budget_and_warn()
        if budget_status == "critical":
            raise HTTPException(
                status_code=402,
                detail="Budget mensual agotado. Aumentar MONTHLY_BUDGET_USD en configuración."
            )

    try:
        await DatabasePool.init_db()

        orchestrator = WeeklyOrchestrator(
            run_id=run_id,
            organization_id=request.organization_id,
            dry_run=request.dry_run,
        )

        result = await orchestrator.run(
            formats_override=request.formats_override
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error en POST /generate/weekly run_id=%s", run_id)
        raise HTTPException(status_code=500, detail=f"Error en generación: {str(e)}")


# =============================================================================
# ORQUESTADOR INLINE — Se refactorizará a orchestrator/ en Fase 1.3
# Por ahora vive aquí para tener un MVP funcional sin depender del orquestador.
# =============================================================================

class WeeklyOrchestrator:
    """
    Orquestador del run semanal.

    Esta es la versión MVP (Fase 1.1). Cuando se implemente orchestrator/main.py
    en la tarea 1.3 del roadmap, esta clase se reemplazará por:
        from orchestrator.main import MainOrchestrator
    """

    def __init__(self, run_id: str, organization_id: str, dry_run: bool):
        self.run_id = run_id
        self.organization_id = organization_id
        self.dry_run = dry_run
        self.embedder = get_embedder()
        self.used_chunk_ids: set[str] = set()  # diversidad cross-formato

    async def run(self, formats_override: Optional[list[dict]] = None) -> GenerateResponse:
        """Ejecuta el run semanal completo."""

        # 1. Obtener reglas de generación
        weekly_rules = await self._get_weekly_rules(formats_override)
        logger.info("Run %s: %d reglas de generación", self.run_id, len(weekly_rules))

        # 2. Generar contenido
        pieces_generated = 0
        pieces_failed = 0
        pieces_qa_passed = 0
        pieces_qa_failed = 0
        total_cost = 0.0
        notion_urls: list[str] = []

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_GENERATIONS)

        for rule in weekly_rules:
            formato = rule.get("formato", "reel_cta")
            topico = rule.get("topico", "")
            cantidad = int(rule.get("cantidad", 1))

            logger.info(
                "Run %s: generando %d piezas de '%s' sobre '%s'",
                self.run_id, cantidad, formato, topico
            )

            for i in range(cantidad):
                async with semaphore:
                    try:
                        piece_result = await self._generate_one_piece(
                            formato=formato,
                            topico=topico,
                            piece_index=i,
                        )

                        if piece_result is None:
                            pieces_failed += 1
                            continue

                        pieces_generated += 1
                        total_cost += piece_result.get("cost_usd", 0.0)

                        if piece_result.get("qa_passed"):
                            pieces_qa_passed += 1
                            # Publicar en Notion (si no es dry_run)
                            notion_url = await self._publish_piece(piece_result, formato)
                            if notion_url:
                                notion_urls.append(notion_url)
                        else:
                            pieces_qa_failed += 1
                            logger.info(
                                "Run %s: pieza QA failed (%s): %s",
                                self.run_id, formato, piece_result.get("qa_reason", "")
                            )

                    except Exception as e:
                        logger.error(
                            "Run %s: error generando pieza %d de %s: %s",
                            self.run_id, i, formato, e
                        )
                        pieces_failed += 1

        # 3. Guardar el run en Postgres
        await self._save_run_to_db(
            pieces_generated=pieces_generated,
            pieces_failed=pieces_failed,
            pieces_qa_passed=pieces_qa_passed,
            pieces_qa_failed=pieces_qa_failed,
            total_cost=total_cost,
        )

        # 4. Notificar por Telegram
        await self._send_telegram_summary(
            pieces_generated=pieces_generated,
            pieces_qa_passed=pieces_qa_passed,
            total_cost=total_cost,
        )

        logger.info(
            "Run %s completado: %d generadas, %d QA passed, $%.4f",
            self.run_id, pieces_generated, pieces_qa_passed, total_cost
        )

        return GenerateResponse(
            run_id=self.run_id,
            organization_id=self.organization_id,
            pieces_generated=pieces_generated,
            pieces_failed=pieces_failed,
            pieces_qa_passed=pieces_qa_passed,
            pieces_qa_failed=pieces_qa_failed,
            cost_usd=round(total_cost, 4),
            notion_urls=notion_urls,
            dry_run=self.dry_run,
        )

    async def _get_weekly_rules(
        self,
        formats_override: Optional[list[dict]],
    ) -> list[dict]:
        """
        Lee las reglas de generación. En orden de prioridad:
        1. formats_override (si se pasa en el request)
        2. Notion Weekly Rules (cuando esté implementado en Fase 1.2)
        3. DEFAULT_WEEKLY_RULES como fallback
        """
        if formats_override:
            logger.info("Usando formats_override del request")
            return formats_override

        # TODO Fase 1.2: Leer de Notion
        # try:
        #     from storage.notion_client import NotionClient
        #     notion = NotionClient(organization_id=self.organization_id)
        #     rules = await notion.get_weekly_rules()
        #     if rules:
        #         return rules
        # except Exception as e:
        #     logger.warning("No se pudieron leer Weekly Rules de Notion: %s. Usando defaults.", e)

        logger.info("Usando DEFAULT_WEEKLY_RULES (Notion no implementado aún)")
        return DEFAULT_WEEKLY_RULES

    async def _generate_one_piece(
        self,
        formato: str,
        topico: str,
        piece_index: int,
    ) -> Optional[dict]:
        """
        Genera una pieza de contenido:
        1. Busca el chunk más relevante (con diversidad)
        2. Obtiene el SOP del formato
        3. Llama al agente correspondiente
        4. Retorna el resultado con metadatos
        """
        if self.dry_run:
            # En dry_run: simular sin llamar al LLM
            return {
                "formato": formato,
                "topico": topico,
                "content": {"hook": f"[DRY RUN] Pieza {piece_index + 1} de {formato} sobre {topico}"},
                "chunk_id": None,
                "cost_usd": 0.0,
                "qa_passed": True,
                "qa_reason": "",
            }

        # Generar ángulo de búsqueda variado según el índice
        search_query = await self._generate_search_angle(topico, piece_index)

        # Buscar chunk relevante con diversidad
        chunk = await self._find_best_chunk(search_query, formato)
        if not chunk:
            logger.warning("No se encontró chunk para '%s' (formato: %s)", topico, formato)
            return None

        # Obtener SOP
        sop = await self._get_sop(formato)

        # Llamar al agente
        try:
            from poc.agents.registry import get_agent
            from poc.agents.base_agent import AgentInput

            agent = get_agent(formato)
            agent_input = AgentInput(
                topic=topico,
                context=chunk.get("content", ""),
                sop=sop,
                extra={"cta": "Sígueme para más contenido"},
            )

            output = await agent.run(agent_input)

            # Marcar chunk como usado (diversity tracking)
            chunk_id = chunk.get("chunk_id")
            if chunk_id:
                self.used_chunk_ids.add(chunk_id)
                from agent.tools import mark_chunk_used
                await mark_chunk_used(chunk_id)

            return {
                "formato":     formato,
                "topico":      topico,
                "content":     output.data,
                "chunk_id":    chunk_id,
                "document_id": chunk.get("document_id"),
                "cost_usd":    output.cost_usd,
                "qa_passed":   output.qa_passed,
                "qa_reason":   output.qa_notes if not output.qa_passed else "",
                "model_used":  get_active_model(),
            }

        except Exception as e:
            logger.error("Error en agente '%s': %s", formato, e)
            return None

    async def _generate_search_angle(self, topico: str, index: int) -> str:
        """
        Genera ángulos de búsqueda variados para el mismo tópico.
        Cada pieza del mismo tópico buscará desde un ángulo diferente.

        En Fase 1.3 esto se reemplaza por el Search Intent Generator (LLM).
        Por ahora usa variaciones predefinidas.
        """
        angles = [
            topico,
            f"objeciones y miedos relacionados con {topico}",
            f"estrategias exitosas para {topico}",
            f"errores comunes en {topico}",
            f"casos reales de {topico}",
        ]
        return angles[index % len(angles)]

    async def _find_best_chunk(
        self,
        query: str,
        formato: str,
    ) -> Optional[dict]:
        """
        Busca el chunk más relevante con diversidad.
        Excluye chunks ya usados en este run.
        """
        try:
            embedding, _ = await self.embedder.generate_embedding(query)

            from agent.tools import hybrid_search

            results = await hybrid_search(
                query=query,
                query_embedding=embedding,
                limit=10,
            )

            # Filtrar chunks ya usados en este run (diversidad cross-formato)
            fresh_results = [
                r for r in results
                if r.chunk_id not in self.used_chunk_ids
            ]

            if not fresh_results:
                # Si todos están usados, tomar el mejor sin filtro
                fresh_results = results

            if not fresh_results:
                return None

            best = fresh_results[0]
            return {
                "chunk_id":    best.chunk_id,
                "document_id": best.document_id,
                "content":     best.content,
                "score":       best.score,
                "metadata":    best.metadata,
            }

        except Exception as e:
            logger.error("Error en búsqueda para '%s': %s", query, e)
            return None

    async def _get_sop(self, formato: str) -> Optional[str]:
        """
        Obtiene el SOP para el formato desde Notion o desde archivos locales.
        Fase 1: lee de config/sops/*.txt (implementación simple).
        Fase 1.2: leer de Notion.
        """
        import os

        # Intentar leer de config/sops/ primero
        sop_path = f"config/sops/{formato}.txt"
        if os.path.exists(sop_path):
            try:
                with open(sop_path, encoding="utf-8") as f:
                    return f.read().strip()
            except Exception as e:
                logger.warning("No se pudo leer SOP de '%s': %s", sop_path, e)

        # TODO Fase 1.2: Leer de Notion
        # try:
        #     from storage.notion_client import NotionClient
        #     notion = NotionClient(organization_id=self.organization_id)
        #     return await notion.get_sop(formato)
        # except Exception:
        #     pass

        return None  # Sin SOP los agentes usan su default_sop

    async def _publish_piece(
        self,
        piece: dict,
        formato: str,
    ) -> Optional[str]:
        """
        Publica una pieza en Notion.
        Fase 1: stub que guarda en Postgres solamente.
        Fase 1.2: implementar publicación real en Notion.
        """
        # Guardar en Postgres como generated_content
        try:
            import json

            async with get_db_connection() as conn:
                notion_status = "Propuesta" if not self.dry_run else "DryRun"
                await conn.execute(
                    """
                    INSERT INTO generated_content
                        (run_id, chunk_id, document_id, content_type, content,
                         qa_passed, qa_reason, cost_usd, model_used, notion_status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    self.run_id,
                    piece.get("chunk_id"),
                    piece.get("document_id"),
                    formato,
                    json.dumps(piece.get("content", {})),
                    piece.get("qa_passed", False),
                    piece.get("qa_reason", ""),
                    piece.get("cost_usd", 0.0),
                    piece.get("model_used", config.DEFAULT_MODEL),
                    notion_status,
                )
        except Exception as e:
            logger.warning("No se pudo guardar pieza en Postgres: %s", e)

        # TODO Fase 1.2: Publicar en Notion real
        # try:
        #     from storage.notion_client import NotionClient
        #     notion = NotionClient(organization_id=self.organization_id)
        #     page_id, url = await notion.publish_piece(piece, formato)
        #     return url
        # except Exception as e:
        #     logger.error("Error publicando en Notion: %s", e)

        return None  # Sin Notion aún, no hay URL

    async def _save_run_to_db(
        self,
        pieces_generated: int,
        pieces_failed: int,
        pieces_qa_passed: int,
        pieces_qa_failed: int,
        total_cost: float,
    ) -> None:
        """Guarda el resultado del run en la tabla weekly_runs."""
        try:
            from datetime import datetime

            async with get_db_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO weekly_runs
                        (id, run_date, pieces_generated, pieces_failed,
                         pieces_qa_passed, pieces_qa_failed, total_cost_usd,
                         status, completed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'completed', NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        pieces_generated = EXCLUDED.pieces_generated,
                        pieces_failed    = EXCLUDED.pieces_failed,
                        pieces_qa_passed = EXCLUDED.pieces_qa_passed,
                        pieces_qa_failed = EXCLUDED.pieces_qa_failed,
                        total_cost_usd   = EXCLUDED.total_cost_usd,
                        status           = 'completed',
                        completed_at     = NOW()
                    """,
                    self.run_id,
                    date.today(),
                    pieces_generated,
                    pieces_failed,
                    pieces_qa_passed,
                    pieces_qa_failed,
                    round(total_cost, 6),
                )
        except Exception as e:
            logger.error("Error guardando run %s en DB: %s", self.run_id, e)

    async def _send_telegram_summary(
        self,
        pieces_generated: int,
        pieces_qa_passed: int,
        total_cost: float,
    ) -> None:
        """Envía resumen del run por Telegram."""
        if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
            return

        try:
            from monitoring.telegram import TelegramNotifier
            telegram = TelegramNotifier()

            approval_rate = (
                round(pieces_qa_passed / pieces_generated * 100, 1)
                if pieces_generated > 0 else 0
            )

            message = (
                f"📊 *Run semanal Novolabs — {date.today().strftime('%d %b %Y')}*\n\n"
                f"{'✅' if pieces_qa_passed > 0 else '⚠️'} "
                f"{pieces_generated} piezas generadas\n"
                f"👍 {pieces_qa_passed} aprobadas por QA ({approval_rate}%)\n"
                f"{'🚫 ' + str(self.dry_run and '[DRY RUN]' or '') if self.dry_run else ''}\n\n"
                f"💰 Costo total: ${total_cost:.2f}\n\n"
                f"⏳ {pieces_qa_passed} piezas esperando revisión en Notion"
            )

            await telegram.send_message(message)
        except Exception as e:
            logger.warning("No se pudo enviar Telegram: %s", e)