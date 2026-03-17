import json
import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from poc.config import config
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

    # Scores de debug (opcionales, útiles para tuning)
    vector_score:   float = 0.0
    entity_score:   float = 0.0
    diversity_score: float = 1.0

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

    @property
    def entities(self) -> list[dict]:
        return self.metadata.get("entities", [])

    @property
    def entity_names(self) -> list[str]:
        return [e.get("name", "").lower() for e in self.entities]

    @property
    def relationships(self) -> list[dict]:
        return self.metadata.get("relationships", [])


# =============================================================================
# VECTOR SEARCH CON DIVERSIDAD (existente, mejorado)
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
    Sin cambios respecto a v2.0 — base sólida sobre la que se construye la búsqueda de entidades.
    """
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    diversity_factor = 1.0 - diversity_penalty

    conditions = ["c.metadata->>'is_deleted' != 'true'", "c.embedding IS NOT NULL"]
    params: list = [embedding_str, limit]
    param_idx = 3

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

    if topics_filter:
        topic_clauses = [f"c.metadata->>'topics' LIKE '%{t}%'" for t in topics_filter]
        conditions.append("(" + " OR ".join(topic_clauses) + ")")

    if exclude_chunk_ids:
        ids_sql = ", ".join(f"'{cid}'" for cid in exclude_chunk_ids)
        conditions.append(f"c.id NOT IN ({ids_sql})")

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            c.id AS chunk_id, c.document_id, d.title AS document_title,
            c.content, c.metadata,
            1 - (c.embedding <=> $1::vector) AS base_score,
            CASE
                WHEN (c.metadata->>'last_used_at') IS NOT NULL
                  AND (c.metadata->>'last_used_at')::DATE
                      > NOW() - INTERVAL '{diversity_lookback_days} days'
                THEN {diversity_factor}
                ELSE 1.0
            END AS diversity_factor,
            (1 - (c.embedding <=> $1::vector)) * (
                CASE
                    WHEN (c.metadata->>'last_used_at') IS NOT NULL
                      AND (c.metadata->>'last_used_at')::DATE
                          > NOW() - INTERVAL '{diversity_lookback_days} days'
                    THEN {diversity_factor}
                    ELSE 1.0
                END
            ) AS final_score
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE {where_clause}
        ORDER BY final_score DESC
        LIMIT $2
    """

    async with get_db_connection() as conn:
        rows = await conn.fetch(query, *params)

    return [
        SearchResult(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            document_title=row["document_title"],
            content=row["content"],
            score=float(row["final_score"]),
            vector_score=float(row["base_score"]),
            diversity_score=float(row["diversity_factor"]),
            metadata=dict(row["metadata"]) if row["metadata"] else {},
        )
        for row in rows
    ]


# =============================================================================
# ENTITY SEARCH — NUEVO
# Búsqueda directa por nombre de entidad en metadata JSONB
# =============================================================================

async def entity_search(
    entity_names: list[str],
    limit: int = 10,
    domain_filter: Optional[str] = None,
    emotion_filter: Optional[str] = None,
    min_entity_matches: int = 1,
) -> list[SearchResult]:
    """
    Busca chunks que contengan entidades específicas en su metadata.

    Permite queries semánticas de tipo "Graph-in-a-Box":
        - "Dame chunks donde se habla de 'Cierre de ventas'"
        - "Dame chunks con entidad 'Objeción de precio' y emoción 'frustración'"
        - "Dame chunks que mencionen tanto 'PMF' como 'Inversores'"

    Args:
        entity_names:        Lista de nombres de entidad a buscar
        limit:               Máximo de resultados
        domain_filter:       Filtrar por dominio
        emotion_filter:      Filtrar por emoción dominante
        min_entity_matches:  Mínimo de entidades del filtro que debe tener el chunk

    Returns:
        Chunks ordenados por cantidad de entidades coincidentes (más relevantes primero)
    """
    if not entity_names:
        return []

    # Normalizar nombres a minúsculas para comparación insensible a mayúsculas
    names_lower = [n.lower() for n in entity_names]

    # Construir cláusulas WHERE: cada nombre genera una condición LIKE sobre entities
    entity_conditions = []
    for name in names_lower:
        # Busca en el array JSONB de entities por nombre
        entity_conditions.append(
            f"EXISTS (SELECT 1 FROM jsonb_array_elements(c.metadata->'entities') AS e "
            f"WHERE lower(e->>'name') LIKE '%{name}%')"
        )

    # Al menos min_entity_matches de las condiciones deben cumplirse
    if min_entity_matches == 1:
        entity_where = "(" + " OR ".join(entity_conditions) + ")"
    else:
        # Para AND estricto (todas las entidades presentes)
        entity_where = "(" + " AND ".join(entity_conditions) + ")"

    conditions = [
        "c.metadata->>'is_deleted' != 'true'",
        "jsonb_array_length(c.metadata->'entities') > 0",
        entity_where,
    ]

    if domain_filter:
        conditions.append(f"c.metadata->>'domain' = '{domain_filter}'")
    if emotion_filter:
        conditions.append(f"c.metadata->>'emotion' = '{emotion_filter}'")

    where = " AND ".join(conditions)

    # Score: número de entidades coincidentes (más coincidencias = más relevante)
    match_count_expr = " + ".join(
        f"CASE WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(c.metadata->'entities') AS e "
        f"WHERE lower(e->>'name') LIKE '%{name}%') THEN 1 ELSE 0 END"
        for name in names_lower
    )

    async with get_db_connection() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                c.id AS chunk_id,
                c.document_id,
                d.title AS document_title,
                c.content,
                c.metadata,
                ({match_count_expr}) AS entity_match_count
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE {where}
            ORDER BY entity_match_count DESC, c.created_at DESC
            LIMIT $1
            """,
            limit,
        )

    return [
        SearchResult(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            document_title=row["document_title"],
            content=row["content"],
            score=float(row["entity_match_count"]) / len(entity_names),
            entity_score=float(row["entity_match_count"]) / len(entity_names),
            metadata=dict(row["metadata"]) if row["metadata"] else {},
        )
        for row in rows
    ]


# =============================================================================
# HYBRID SEARCH CON ENTIDADES — NUEVO (inspirado en LightRAG)
# =============================================================================

async def hybrid_search_with_entities(
    query: str,
    query_embedding: list[float],
    query_entities: Optional[list[str]] = None,
    limit: int = 5,
    domain_filter: Optional[str] = None,
    source_type_filter: Optional[str] = None,
    diversity_lookback_days: int = 30,
    # Pesos para combinar los tres scores
    weight_vector: float = 0.5,
    weight_entity: float = 0.3,
    weight_diversity: float = 0.2,
) -> list[SearchResult]:
    """
    Búsqueda híbrida semántica de 3 capas inspirada en LightRAG.

    ALGORITMO:
        1. Capa vectorial (peso 50%):
           Trae los top-20 chunks por similitud coseno

        2. Capa de entidades (peso 30%):
           Para cada chunk, calcula cuántas de sus entidades coinciden con
           query_entities (entidades extraídas de la query o de Weekly Rules).
           Un chunk con 3 entidades coincidentes obtiene mejor score que uno con 1.

        3. Capa de diversidad (peso 20%):
           Penaliza chunks usados en los últimos N días o que compartan
           demasiadas entidades con chunks ya seleccionados en este run.

    Score final = (vector_score * w_vector) + (entity_score * w_entity) + (diversity_score * w_diversity)

    Args:
        query_entities: Lista de nombres de entidad relevantes para la query.
            Puede venir de:
            - Extracción LLM de la query (recomendado)
            - Weekly Rules de Notion
            - Topics del formato a generar
            Si es None, se comporta como vector_search_with_diversity estándar.

    Returns:
        Lista de SearchResult ordenados por score final combinado, deduplicados.
    """
    # Si no hay query_entities, fallback directo a vector search
    if not query_entities:
        return await _hybrid_search_postgres_only(
            query=query,
            query_embedding=query_embedding,
            limit=limit,
            domain_filter=domain_filter,
            source_type_filter=source_type_filter,
            diversity_lookback_days=diversity_lookback_days,
        )

    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    entity_names_lower = [n.lower() for n in query_entities]

    # Construir score de entidades: 1 punto por cada entidad coincidente, normalizado
    entity_score_parts = []
    for name in entity_names_lower:
        entity_score_parts.append(
            f"CASE WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(c.metadata->'entities') AS e "
            f"WHERE lower(e->>'name') LIKE '%{name}%') THEN 1 ELSE 0 END"
        )

    n_entities = len(entity_names_lower)
    entity_score_expr = f"({' + '.join(entity_score_parts)})::float / {n_entities}" if entity_score_parts else "0.0"

    diversity_factor = 0.70

    filter_clauses = ["c.embedding IS NOT NULL", "c.metadata->>'is_deleted' != 'true'"]
    if domain_filter:
        filter_clauses.append(f"c.metadata->>'domain' = '{domain_filter}'")
    if source_type_filter:
        filter_clauses.append(f"c.metadata->>'source_type' = '{source_type_filter}'")

    where = " AND ".join(filter_clauses)

    query_sql = f"""
    WITH base AS (
        SELECT
            c.id AS chunk_id,
            c.document_id,
            d.title AS document_title,
            c.content,
            c.metadata,

            -- Score vectorial
            1 - (c.embedding <=> '{embedding_str}'::vector) AS vector_score,

            -- Score de entidades (estilo LightRAG)
            {entity_score_expr} AS entity_score,

            -- Score de diversidad temporal
            CASE
                WHEN (c.metadata->>'last_used_at') IS NOT NULL
                  AND (c.metadata->>'last_used_at')::DATE
                      > NOW() - INTERVAL '{diversity_lookback_days} days'
                THEN {diversity_factor}
                ELSE 1.0
            END AS diversity_factor

        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE {where}
    ),
    scored AS (
        SELECT *,
            -- Score final ponderado
            (vector_score * {weight_vector})
            + (entity_score * {weight_entity})
            + (diversity_factor * {weight_diversity} - {weight_diversity} + {weight_diversity})
            -- Nota: diversity_factor es 0.7 o 1.0, lo normalizamos al peso
            AS final_score
        FROM base
        WHERE vector_score > 0.2  -- Filtrar ruido extremo
    )
    SELECT * FROM scored
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
            vector_score=float(row["vector_score"]),
            entity_score=float(row["entity_score"]),
            diversity_score=float(row["diversity_factor"]),
            metadata=dict(row["metadata"]) if row["metadata"] else {},
        )
        for row in rows
    ]


# =============================================================================
# HYBRID SEARCH ESTÁNDAR (Postgres solo, Fase 1)
# =============================================================================

async def hybrid_search(
    query: str,
    query_embedding: list[float],
    limit: int = 5,
    domain_filter: Optional[str] = None,
    source_type_filter: Optional[str] = None,
    topics_filter: Optional[list[str]] = None,
    diversity_lookback_days: int = 30,
    query_entities: Optional[list[str]] = None,
) -> list[SearchResult]:
    """
    Búsqueda híbrida. Usa entidades si están disponibles, sino RRF estándar.

    Si ENABLE_GRAPH=true (Fase 2+), enriquece con Neo4j episode_ids.
    """
    if config.ENABLE_GRAPH:
        return await _hybrid_search_with_graph(
            query=query, query_embedding=query_embedding,
            limit=limit, domain_filter=domain_filter,
        )

    # Si hay entidades disponibles, usar la búsqueda enriquecida
    if query_entities:
        return await hybrid_search_with_entities(
            query=query,
            query_embedding=query_embedding,
            query_entities=query_entities,
            limit=limit,
            domain_filter=domain_filter,
            source_type_filter=source_type_filter,
            diversity_lookback_days=diversity_lookback_days,
        )

    return await _hybrid_search_postgres_only(
        query=query, query_embedding=query_embedding,
        limit=limit, domain_filter=domain_filter,
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
    topics_filter: Optional[list[str]] = None,
    diversity_lookback_days: int = 30,
) -> list[SearchResult]:
    """RRF (Reciprocal Rank Fusion) entre búsqueda vectorial y full-text."""
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    filter_clauses = ["c.embedding IS NOT NULL", "c.metadata->>'is_deleted' != 'true'"]
    if domain_filter:
        filter_clauses.append(f"c.metadata->>'domain' = '{domain_filter}'")
    if source_type_filter:
        filter_clauses.append(f"c.metadata->>'source_type' = '{source_type_filter}'")
    if topics_filter:
        topic_clauses = [f"c.metadata->>'topics' LIKE '%{t}%'" for t in topics_filter]
        filter_clauses.append("(" + " OR ".join(topic_clauses) + ")")

    where = " AND ".join(filter_clauses)
    diversity_factor = 0.70

    rrf_query = f"""
    WITH vector_ranked AS (
        SELECT c.id AS chunk_id, c.document_id, d.title AS document_title,
               c.content, c.metadata,
               ROW_NUMBER() OVER (ORDER BY c.embedding <=> '{embedding_str}'::vector) AS rank
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE {where}
        LIMIT 50
    ),
    fulltext_ranked AS (
        SELECT c.id AS chunk_id,
               ROW_NUMBER() OVER (
                   ORDER BY ts_rank(to_tsvector('spanish', c.content),
                            plainto_tsquery('spanish', $1)) DESC
               ) AS rank
        FROM chunks c
        WHERE {where}
          AND to_tsvector('spanish', c.content) @@ plainto_tsquery('spanish', $1)
        LIMIT 50
    ),
    rrf AS (
        SELECT v.chunk_id, v.document_id, v.document_title, v.content, v.metadata,
               COALESCE(1.0 / (60 + v.rank), 0) +
               COALESCE(1.0 / (60 + f.rank), 0) AS rrf_score
        FROM vector_ranked v
        LEFT JOIN fulltext_ranked f USING (chunk_id)
    )
    SELECT chunk_id, document_id, document_title, content, metadata,
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
    query: str, query_embedding: list[float],
    limit: int, domain_filter: Optional[str],
) -> list[SearchResult]:
    """Fase 2+: enriquece con Neo4j."""
    try:
        from agent.graph_utils import GraphClient
        graph = GraphClient.get_client()
        episode_ids = await graph.search_episodes(query, limit=20)
        if not episode_ids:
            logger.warning("hybrid_search_with_graph: no episode_ids, fallback a Postgres")
            return await _hybrid_search_postgres_only(
                query=query, query_embedding=query_embedding, limit=limit,
                domain_filter=domain_filter, source_type_filter=None,
            )
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        ids_sql = ", ".join(f"'{eid}'" for eid in episode_ids)
        async with get_db_connection() as conn:
            rows = await conn.fetch(
                f"""
                SELECT c.id AS chunk_id, c.document_id, d.title AS document_title,
                       c.content, c.metadata,
                       1 - (c.embedding <=> '{embedding_str}'::vector) AS final_score
                FROM chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE d.graphiti_episode_id IN ({ids_sql})
                  AND c.metadata->>'is_deleted' != 'true'
                ORDER BY final_score DESC
                LIMIT $1
                """, limit
            )
        return [
            SearchResult(
                chunk_id=str(r["chunk_id"]), document_id=str(r["document_id"]),
                document_title=r["document_title"], content=r["content"],
                score=float(r["final_score"]),
                metadata=dict(r["metadata"]) if r["metadata"] else {},
            ) for r in rows
        ]
    except Exception as e:
        logger.error("hybrid_search_with_graph failed: %s. Fallback a Postgres.", e)
        return await _hybrid_search_postgres_only(
            query=query, query_embedding=query_embedding, limit=limit,
            domain_filter=domain_filter, source_type_filter=None,
        )


# =============================================================================
# FIND SIMILAR BY ENTITIES — NUEVO
# Para el QA Gate: detectar piezas temáticamente duplicadas
# =============================================================================

async def find_similar_by_entities(
    entity_names: list[str],
    exclude_chunk_id: Optional[str] = None,
    similarity_threshold: float = 0.5,
    limit: int = 5,
) -> list[dict]:
    """
    Encuentra chunks que comparten muchas entidades con una lista dada.
    Usado por el QA Gate para detectar si dos piezas generadas hablan de lo mismo.

    Un chunk se considera "similar" si comparte >= similarity_threshold de las entidades.

    Returns:
        Lista de {chunk_id, shared_entities, similarity_score}
    """
    if not entity_names:
        return []

    names_lower = [n.lower() for n in entity_names]
    n_entities = len(names_lower)

    match_count_expr = " + ".join(
        f"CASE WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(c.metadata->'entities') AS e "
        f"WHERE lower(e->>'name') LIKE '%{name}%') THEN 1 ELSE 0 END"
        for name in names_lower
    )

    conditions = [
        "jsonb_array_length(c.metadata->'entities') > 0",
        "c.metadata->>'is_deleted' != 'true'",
    ]
    if exclude_chunk_id:
        conditions.append(f"c.id != '{exclude_chunk_id}'")

    where = " AND ".join(conditions)

    async with get_db_connection() as conn:
        rows = await conn.fetch(
            f"""
            SELECT c.id AS chunk_id,
                   ({match_count_expr}) AS match_count
            FROM chunks c
            WHERE {where}
              AND ({match_count_expr}) >= {max(1, int(n_entities * similarity_threshold))}
            ORDER BY match_count DESC
            LIMIT $1
            """,
            limit,
        )

    return [
        {
            "chunk_id": str(row["chunk_id"]),
            "similarity_score": float(row["match_count"]) / n_entities,
            "shared_entity_count": int(row["match_count"]),
        }
        for row in rows
    ]


# =============================================================================
# MARK CHUNK AS USED
# =============================================================================

async def mark_chunk_used(chunk_id: str) -> None:
    """Actualiza used_count y last_used_at en la metadata del chunk."""
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
# FIND SIMILAR CHUNKS (para QA Gate por vector)
# =============================================================================

async def find_similar_chunks(
    embedding: list[float],
    threshold: float = 0.85,
    exclude_chunk_id: Optional[str] = None,
) -> list[dict]:
    """Busca chunks con embedding muy similar. Usado por el QA Gate."""
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    conditions = [f"1 - (c.embedding <=> '{embedding_str}'::vector) > {threshold}"]
    if exclude_chunk_id:
        conditions.append(f"c.id != '{exclude_chunk_id}'")
    where = " AND ".join(conditions)
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            f"""
            SELECT c.id AS chunk_id,
                   1 - (c.embedding <=> '{embedding_str}'::vector) AS similarity
            FROM chunks c
            WHERE {where}
            ORDER BY similarity DESC
            LIMIT 5
            """
        )
    return [{"chunk_id": str(r["chunk_id"]), "score": float(r["similarity"])} for r in rows]