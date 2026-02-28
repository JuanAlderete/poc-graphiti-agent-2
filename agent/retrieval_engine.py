"""
Retrieval Engine Híbrido Real: Neo4j → Postgres.

Flujo:
    1. Busca en Graphiti (Neo4j) → obtiene lista de edges/facts con episode metadata
    2. Extrae los episode names de los resultados del grafo
    3. Busca en Postgres los documentos que coinciden con esos episode names
    4. Retorna los top chunks de esos documentos, enriquecidos con el fact del grafo

Diferencia con hybrid_search (existente):
    - hybrid_search (existente): combina vector cosine + FTS en Postgres solamente.
      No usa Neo4j para decidir qué documentos son relevantes.
    - hybrid_real (este): usa Neo4j para navegación conceptual, luego va a Postgres
      para obtener el texto literal de los documentos que el grafo identificó como relevantes.

Cuándo usar cada uno:
    - hybrid_search: queries semánticas directas ("qué es PMF")
    - hybrid_real: queries relacionales ("qué dijo alguien sobre X", "qué documentos mencionan Y")
"""
import json
import logging
from typing import List, Optional

from agent.db_utils import get_db_connection
from agent.graph_utils import GraphClient
from agent.models import SearchResult
from ingestion.embedder import get_embedder

logger = logging.getLogger(__name__)


class RetrievalEngine:
    """
    Motor de búsqueda híbrido que combina Neo4j y Postgres.
    """

    def __init__(self, graph_results_limit: int = 5, chunks_per_episode: int = 2):
        """
        Args:
            graph_results_limit: Cuántos resultados pedir a Graphiti.
            chunks_per_episode: Cuántos chunks traer de Postgres por episodio encontrado.
        """
        self.graph_results_limit = graph_results_limit
        self.chunks_per_episode = chunks_per_episode

    async def search(
        self,
        query: str,
        limit: int = 3,
    ) -> List[SearchResult]:
        """
        Búsqueda híbrida real: Neo4j → extrae episode_names → Postgres chunks.

        Args:
            query: Query de búsqueda en lenguaje natural.
            limit: Número total de resultados a retornar.

        Returns:
            Lista de SearchResult enriquecidos con fact (Neo4j) + content (Postgres).
        """
        results: List[SearchResult] = []

        # ── Paso 1: Buscar en Graphiti (Neo4j) ──────────────────────────────
        try:
            graph_raw = await GraphClient.get_client().search(query)
        except Exception:
            logger.exception("Graph search failed in RetrievalEngine, falling back to vector search")
            return await self._fallback_vector_search(query, limit)

        if not graph_raw:
            logger.info("No graph results for '%s', falling back to vector search", query)
            return await self._fallback_vector_search(query, limit)

        # ── Paso 2: Extraer episode names de los resultados del grafo ────────
        # Los resultados de Graphiti son objetos Edge o strings.
        # Extraemos los nombres de los episodios de origen.
        episode_names = self._extract_episode_names(graph_raw)

        logger.info(
            "Graph search for '%s': %d results → %d unique episodes",
            query, len(graph_raw), len(episode_names)
        )

        if not episode_names:
            logger.info("Could not extract episode names from graph results, falling back")
            return await self._fallback_vector_search(query, limit)

        # ── Paso 3: Buscar chunks en Postgres para esos episodios ────────────
        # Cada episode_name corresponde al campo `source` en la tabla `documents`.
        chunks_with_facts = await self._fetch_chunks_for_episodes(
            episode_names=episode_names,
            facts=graph_raw,
            chunks_per_episode=self.chunks_per_episode,
        )

        # ── Paso 4: Si hay pocos resultados, complementar con vector search ──
        if len(chunks_with_facts) < limit:
            vector_results = await self._fallback_vector_search(query, limit - len(chunks_with_facts))
            # Evitar duplicados por contenido
            existing_contents = {r.content[:100] for r in chunks_with_facts}
            for vr in vector_results:
                if vr.content[:100] not in existing_contents:
                    chunks_with_facts.append(vr)

        return chunks_with_facts[:limit]

    def _extract_episode_names(self, graph_results: list) -> List[str]:
        """
        Extrae nombres de episodios de los resultados de Graphiti.

        Graphiti retorna objetos de diferentes tipos según la versión.
        Esta función maneja los casos conocidos de graphiti-core 0.12.x.
        """
        names = set()
        for result in graph_results:
            # Caso 1: el resultado tiene atributo episodes (lista de EpisodicNode)
            if hasattr(result, "episodes") and result.episodes:
                for ep in result.episodes:
                    name = getattr(ep, "name", None) or getattr(ep, "source_description", None)
                    if name:
                        names.add(str(name))

            # Caso 2: el resultado tiene atributo source_node_name
            if hasattr(result, "source_node_name") and result.source_node_name:
                names.add(str(result.source_node_name))

            # Caso 3: string representation contiene el nombre
            result_str = str(result)
            if "(" in result_str and ")" in result_str:
                # Graphiti a veces retorna "EntityName (context)"
                potential_name = result_str.split("(")[0].strip()
                if potential_name and len(potential_name) < 100:
                    names.add(potential_name)

        return list(names)

    async def _fetch_chunks_for_episodes(
        self,
        episode_names: List[str],
        facts: list,
        chunks_per_episode: int,
    ) -> List[SearchResult]:
        """
        Para cada episode_name, busca los chunks correspondientes en Postgres.
        Enriquece cada chunk con el fact relacionado del grafo.
        """
        results = []
        facts_by_episode = self._index_facts_by_episode(facts)

        async with get_db_connection() as conn:
            for episode_name in episode_names[:self.graph_results_limit]:
                # Buscar documento por `source` o `title` que coincida con episode_name
                rows = await conn.fetch(
                    """
                    SELECT c.content, c.metadata, d.title, d.source, d.graphiti_episode_id
                    FROM chunks c
                    JOIN documents d ON c.document_id = d.id
                    WHERE
                        d.source ILIKE $1
                        OR d.title ILIKE $1
                        OR d.source ILIKE $2
                    ORDER BY c.chunk_index ASC
                    LIMIT $3
                    """,
                    f"%{episode_name}%",
                    f"{episode_name}%",
                    chunks_per_episode,
                )

                for row in rows:
                    # Fact relacionado del grafo (contexto conceptual)
                    episode_facts = facts_by_episode.get(episode_name, [])
                    fact_context = " | ".join(str(f)[:200] for f in episode_facts[:2]) if episode_facts else ""

                    content_enriched = row["content"]
                    if fact_context:
                        content_enriched = f"[Concepto relacionado: {fact_context}]\n\n{row['content']}"

                    meta = {}
                    if row["metadata"]:
                        try:
                            meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else dict(row["metadata"])
                        except Exception:
                            pass

                    meta["graph_fact"] = fact_context
                    meta["episode_name"] = episode_name
                    meta["graphiti_episode_id"] = row.get("graphiti_episode_id", "")

                    results.append(SearchResult(
                        content=content_enriched,
                        metadata=meta,
                        score=0.85,  # Score fijo alto: viene del grafo semántico
                        source="hybrid_real",
                    ))

        if not results:
            logger.info(
                "No Postgres chunks found for episodes %s. "
                "This may mean the documents were not ingested to Postgres, "
                "or the episode names don't match the document sources.",
                episode_names[:3]
            )

        return results

    def _index_facts_by_episode(self, facts: list) -> dict:
        """Indexa los facts de Graphiti por nombre de episodio para lookup rápido."""
        index = {}
        for fact in facts:
            if hasattr(fact, "episodes") and fact.episodes:
                for ep in fact.episodes:
                    name = getattr(ep, "name", None)
                    if name:
                        if name not in index:
                            index[name] = []
                        index[name].append(fact)
        return index

    async def _fallback_vector_search(self, query: str, limit: int) -> List[SearchResult]:
        """Fallback a búsqueda vectorial cuando el grafo no da resultados."""
        from agent.tools import vector_search_with_diversity
        embedder = get_embedder()
        embedding, _ = await embedder.generate_embedding(query)
        # Búsqueda vectorial sin filtros de diversidad para el fallback
        return await vector_search_with_diversity(embedding, limit=limit)
