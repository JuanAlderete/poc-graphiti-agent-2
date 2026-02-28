"""
agent/tools.py
--------------
Herramientas de búsqueda vectorial para los agentes.

Cambios v2.0 (feedback experto):
- vector_search_with_diversity: penaliza chunks usados en los últimos 30 días
- hybrid_search ahora usa solo Postgres (sin Neo4j en Fase 1)
- mark_chunk_used: actualiza used_count y last_used_at en metadata
- Neo4j solo se usa si ENABLE_GRAPH=true (Fase 2+)
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from agent.config import settings
from agent.db_utils import get_db_connection

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SearchResult:
    chunk_id:       str
    document_id:    str
    document_title: str
    content:        str
    score:          float
    metadata:       dict

    @property
    def source_type(self) -> str:
        return self.metadata.get("source_type", "desconocido")

    @property
    def domain(self) -> str:
        return self.metadata.get("domain", "general")

    @property
    def topics(self) -> list[str]:
        return self.metadata.get("topics", [])

    @property
    def content_level(self) -> int:
        return int(self.metadata.get("content_level", 1))

    @property
    def emotion(self) -> str:
        return self.metadata.get("emotion", "neutral")

    @property
    def used_count(self) -> int:
        return int(self.metadata.get("used_count", 0))


# =============================================================================
# VECTOR SEARCH CON DIVERSIDAD
# =============================================================================

async def vector_search_with_diversity(
    query_embedding: list[float],
    limit: int = 5,
    min_score: float = 0.4,
    domain_filter: Optional[str] = None,
    source_type_filter: Optional[str] = None,
    topics_filter: Optional[list[str]] = None,
    exclude_chunk_ids: Optional[list[str]] = None,
    diversity_lookback_days: int = 30,
    diversity_penalty: float = 0.30,
) -> list[SearchResult]:
    """
    Búsqueda vectorial con penalización de chunks usados recientemente.

    Algoritmo:
    1. Calcula base_score = similaridad coseno con el embedding de la query
    2. Aplica diversity_factor: 0.7 si el chunk fue usado en los últimos N días
    3. Filtra por metadata: domain, source_type, topics
    4. Ordena por score final = base_score * diversity_factor
    5. Solo retorna chunks con score >= min_score ANTES de penalización

    Args:
        query_embedding:        Embedding de la query (1536 dims)
        limit:                  Máximo de resultados a retornar
        min_score:              Score mínimo de relevancia (sin penalización)
        domain_filter:          Filtrar por dominio: marketing | ventas | producto | metodologia
        source_type_filter:     Filtrar por tipo de fuente
        topics_filter:          Filtrar chunks que tengan AL MENOS UNO de estos topics
        exclude_chunk_ids:      Excluir chunks específicos (ya usados en este run)
        diversity_lookback_days: Días a mirar hacia atrás para penalizar
        diversity_penalty:      Fracción a restar del score (0.30 = 30% de penalización)
    """
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    diversity_factor = 1.0 - diversity_penalty

    # Construir cláusulas WHERE dinámicas
    conditions = ["c.metadata->>'is_deleted' != 'true'"]
    params: list = [embedding_str, limit]
    param_idx = 3  # $1=embedding, $2=limit, resto dinámico

    if min_score > 0:
        conditions.append(f"1 - (c.embedding <=> $1::vector) >= {min_score}")

    if domain_filter:
        conditions.append(f"c.metadata->>'domain' = ${param_idx}")
        params.append(domain_filter)
        param_idx += 1

    if source_type_filter:
        conditions.append(f"c.metadata->>'source_type' = ${param_idx}")
        params.append(source_type_filter)
        param_idx += 1

    if topics_filter and len(topics_filter) > 0:
        # Chunk debe tener al menos un topic del filtro
        topics_json = json.dumps(topics_filter)
        conditions.append(f"c.metadata->'topics' ?| array{topics_json.replace('[', '(').replace(']', ')')}")
        # Alternativa más simple: buscar cualquier topic como texto
        topic_clauses = []
        for topic in topics_filter:
            topic_clauses.append(f"c.metadata->>'topics' LIKE '%{topic}%'")
        conditions.append("(" + " OR ".join(topic_clauses) + ")")

    if exclude_chunk_ids:
        ids_sql = ", ".join(f"'{cid}'" for cid in exclude_chunk_ids)
        conditions.append(f"c.id NOT IN ({ids_sql})")

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            c.id                                            AS chunk_id,
            c.document_id,
            d.title                                         AS document_title,
            c.content,
            c.metadata,

            -- Score base de similaridad coseno
            1 - (c.embedding <=> $1::vector)               AS base_score,

            -- Penalizar si fue usado en los últimos {diversity_lookback_days} días
            CASE
                WHEN (c.metadata->>'last_used_at') IS NOT NULL
                  AND (c.metadata->>'last_used_at')::DATE
                      > NOW() - INTERVAL '{diversity_lookback_days} days'
                THEN {diversity_factor}
                ELSE 1.0
            END                                             AS diversity_factor,

            -- Score final
            (1 - (c.embedding <=> $1::vector)) * (
                CASE
                    WHEN (c.metadata->>'last_used_at') IS NOT NULL
                      AND (c.metadata->>'last_used_at')::DATE
                          > NOW() - INTERVAL '{diversity_lookback_days} days'
                    THEN {diversity_factor}
                    ELSE 1.0
                END
            )                                               AS final_score

        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE c.embedding IS NOT NULL
          AND {where_clause}
        ORDER BY final_score DESC
        LIMIT $2
    """

    async with get_db_connection() as conn:
        rows = await conn.fetch(query, *params)

    results = []
    for row in rows:
        metadata = dict(row["metadata"]) if row["metadata"] else {}
        results.append(SearchResult(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            document_title=row["document_title"],
            content=row["content"],
            score=float(row["final_score"]),
            metadata=metadata,
        ))

    logger.debug(
        "vector_search_with_diversity: query retornó %d resultados "
        "(domain=%s, min_score=%.2f, lookback=%dd)",
        len(results), domain_filter, min_score, diversity_lookback_days
    )
    return results


# =============================================================================
# HYBRID SEARCH (Postgres solo, Fase 1)
# En Fase 2+ se puede activar el path Neo4j vía ENABLE_GRAPH=true
# =============================================================================

async def hybrid_search(
    query: str,
    query_embedding: list[float],
    limit: int = 5,
    domain_filter: Optional[str] = None,
    source_type_filter: Optional[str] = None,
    topics_filter: Optional[list[str]] = None,
    diversity_lookback_days: int = 30,
) -> list[SearchResult]:
    """
    Búsqueda híbrida: vectorial + full-text en Postgres.

    En Fase 1: Solo Postgres (ENABLE_GRAPH=false por defecto).
    En Fase 2+: Si ENABLE_GRAPH=true, enriquece con Neo4j episode_ids.

    La búsqueda combina:
    - Similaridad vectorial (embedding cosine)
    - Full-text search en español (tsvector)
    - Penalización por uso reciente (diversity)
    - Reciprocal Rank Fusion (RRF) para combinar scores

    Returns:
        Lista de SearchResult ordenados por score combinado, con diversidad aplicada.
    """
    if settings.enable_graph:
        # Fase 2+: enriquecer con Neo4j
        return await _hybrid_search_with_graph(
            query=query,
            query_embedding=query_embedding,
            limit=limit,
            domain_filter=domain_filter,
        )

    # Fase 1: Solo Postgres (default)
    return await _hybrid_search_postgres_only(
        query=query,
        query_embedding=query_embedding,
        limit=limit,
        domain_filter=domain_filter,
        source_type_filter=source_type_filter,
        topics_filter=topics_filter,
        diversity_lookback_days=diversity_lookback_days,
    )


async def _hybrid_search_postgres_only(
    query: str,
    query_embedding: list[float],
    limit: int,
    domain_filter: Optional[str],
    source_type_filter: Optional[str],
    topics_filter: Optional[list[str]],
    diversity_lookback_days: int,
) -> list[SearchResult]:
    """
    RRF (Reciprocal Rank Fusion) entre búsqueda vectorial y full-text.
    Todo en Postgres, sin dependencias externas.
    """
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    # Filtros compartidos
    filter_clauses = ["c.embedding IS NOT NULL", "c.metadata->>'is_deleted' != 'true'"]
    if domain_filter:
        filter_clauses.append(f"c.metadata->>'domain' = '{domain_filter}'")
    if source_type_filter:
        filter_clauses.append(f"c.metadata->>'source_type' = '{source_type_filter}'")
    if topics_filter:
        topic_clauses = [f"c.metadata->>'topics' LIKE '%{t}%'" for t in topics_filter]
        filter_clauses.append("(" + " OR ".join(topic_clauses) + ")")

    where = " AND ".join(filter_clauses)
    diversity_factor = 0.70  # penalización 30% para chunks usados recientemente

    rrf_query = f"""
    WITH vector_ranked AS (
        SELECT
            c.id AS chunk_id,
            c.document_id,
            d.title AS document_title,
            c.content,
            c.metadata,
            ROW_NUMBER() OVER (
                ORDER BY c.embedding <=> '{embedding_str}'::vector
            ) AS rank
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE {where}
        LIMIT 50
    ),
    fulltext_ranked AS (
        SELECT
            c.id AS chunk_id,
            ROW_NUMBER() OVER (
                ORDER BY ts_rank(
                    to_tsvector('spanish', c.content),
                    plainto_tsquery('spanish', $1)
                ) DESC
            ) AS rank
        FROM chunks c
        WHERE {where}
          AND to_tsvector('spanish', c.content) @@ plainto_tsquery('spanish', $1)
        LIMIT 50
    ),
    rrf AS (
        SELECT
            v.chunk_id,
            v.document_id,
            v.document_title,
            v.content,
            v.metadata,
            -- RRF clásico: 1/(k + rank), k=60 es el valor estándar
            COALESCE(1.0 / (60 + v.rank), 0) +
            COALESCE(1.0 / (60 + f.rank), 0) AS rrf_score
        FROM vector_ranked v
        LEFT JOIN fulltext_ranked f USING (chunk_id)
    )
    SELECT
        chunk_id,
        document_id,
        document_title,
        content,
        metadata,
        rrf_score * (
            CASE
                WHEN (metadata->>'last_used_at') IS NOT NULL
                  AND (metadata->>'last_used_at')::DATE
                      > NOW() - INTERVAL '{diversity_lookback_days} days'
                THEN {diversity_factor}
                ELSE 1.0
            END
        ) AS final_score
    FROM rrf
    ORDER BY final_score DESC
    LIMIT $2
    """

    async with get_db_connection() as conn:
        rows = await conn.fetch(rrf_query, query, limit)

    return [
        SearchResult(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            document_title=row["document_title"],
            content=row["content"],
            score=float(row["final_score"]),
            metadata=dict(row["metadata"]) if row["metadata"] else {},
        )
        for row in rows
    ]


async def _hybrid_search_with_graph(
    query: str,
    query_embedding: list[float],
    limit: int,
    domain_filter: Optional[str],
) -> list[SearchResult]:
    """
    Fase 2+: enriquece la búsqueda con episode_ids de Neo4j.
    Solo se llama si ENABLE_GRAPH=true en config.
    """
    try:
        from agent.graph_utils import GraphClient
        graph = GraphClient.get_client()

        # Buscar episode_ids relevantes en Neo4j
        episode_ids = await graph.search_episodes(query, limit=20)
        if not episode_ids:
            logger.warning("hybrid_search_with_graph: Neo4j no retornó episode_ids, fallback a Postgres")
            return await _hybrid_search_postgres_only(
                query=query,
                query_embedding=query_embedding,
                limit=limit,
                domain_filter=domain_filter,
                source_type_filter=None,
                topics_filter=None,
                diversity_lookback_days=30,
            )

        # Filtrar chunks en Postgres que correspondan a esos episodes
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        ids_sql = ", ".join(f"'{eid}'" for eid in episode_ids)

        query_sql = f"""
            SELECT
                c.id AS chunk_id,
                c.document_id,
                d.title AS document_title,
                c.content,
                c.metadata,
                1 - (c.embedding <=> '{embedding_str}'::vector) AS final_score
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE d.graphiti_episode_id IN ({ids_sql})
              AND c.metadata->>'is_deleted' != 'true'
            ORDER BY final_score DESC
            LIMIT $1
        """

        async with get_db_connection() as conn:
            rows = await conn.fetch(query_sql, limit)

        return [
            SearchResult(
                chunk_id=str(row["chunk_id"]),
                document_id=str(row["document_id"]),
                document_title=row["document_title"],
                content=row["content"],
                score=float(row["final_score"]),
                metadata=dict(row["metadata"]) if row["metadata"] else {},
            )
            for row in rows
        ]

    except Exception as e:
        logger.error("hybrid_search_with_graph falló: %s. Fallback a Postgres.", e)
        return await _hybrid_search_postgres_only(
            query=query,
            query_embedding=query_embedding,
            limit=limit,
            domain_filter=domain_filter,
            source_type_filter=None,
            topics_filter=None,
            diversity_lookback_days=30,
        )


# =============================================================================
# MARK CHUNK AS USED
# =============================================================================

async def mark_chunk_used(chunk_id: str) -> None:
    """
    Registra que un chunk fue usado para generar contenido.
    Actualiza used_count y last_used_at en la metadata del chunk.
    Esto es lo que permite el Diversity Selector funcionar sin tabla extra.
    """
    async with get_db_connection() as conn:
        await conn.execute(
            """
            UPDATE chunks
            SET metadata = metadata || jsonb_build_object(
                'used_count',   COALESCE((metadata->>'used_count')::INTEGER, 0) + 1,
                'last_used_at', NOW()::TEXT
            )
            WHERE id = $1
            """,
            UUID(chunk_id),
        )
    logger.debug("mark_chunk_used: chunk %s marcado como usado", chunk_id)


# =============================================================================
# SIMILARITY SEARCH SIMPLE (para QA Gate - detectar piezas similares)
# =============================================================================

async def find_similar_chunks(
    embedding: list[float],
    threshold: float = 0.85,
    exclude_chunk_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> list[dict]:
    """
    Busca chunks o contenido generado con embedding muy similar.
    Usado por el QA Gate para detectar piezas duplicadas en un mismo run.

    Returns:
        Lista de {chunk_id, score} con score > threshold.
    """
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

    conditions = [f"1 - (c.embedding <=> '{embedding_str}'::vector) > {threshold}"]
    if exclude_chunk_id:
        conditions.append(f"c.id != '{exclude_chunk_id}'")

    where = " AND ".join(conditions)

    async with get_db_connection() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                c.id AS chunk_id,
                1 - (c.embedding <=> '{embedding_str}'::vector) AS similarity
            FROM chunks c
            WHERE {where}
            ORDER BY similarity DESC
            LIMIT 5
            """
        )

    return [{"chunk_id": str(row["chunk_id"]), "score": float(row["similarity"])} for row in rows]