import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from uuid import UUID

import asyncpg

from poc.config import config

logger = logging.getLogger(__name__)


class DatabasePool:
    _pool: Optional[asyncpg.Pool] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    async def get_pool(cls) -> asyncpg.Pool:
        current_loop = asyncio.get_running_loop()

        if cls._pool is not None:
            if cls._loop is not current_loop or (cls._loop and cls._loop.is_closed()):
                logger.warning("Event loop cambió — reseteando pool de DB.")
                try:
                    await cls._pool.close()
                except Exception:
                    pass
                cls._pool = None
                cls._loop = None

        if cls._pool is None:
            db_host = config.POSTGRES_HOST
            # Fix para Windows/Docker: localhost a veces resuelve IPv6 ::1 y falla
            if db_host == "localhost":
                db_host = "127.0.0.1"

            cls._pool = await asyncpg.create_pool(
                user=config.POSTGRES_USER,
                password=config.POSTGRES_PASSWORD,
                database=config.POSTGRES_DB,
                host=db_host,
                port=config.POSTGRES_PORT,
                min_size=2,
                max_size=10,
                command_timeout=30,
                init=_register_vector_codec,
            )
            cls._loop = current_loop
            logger.info("Pool de DB creado (min=2, max=10, host=%s).", config.POSTGRES_HOST)

        return cls._pool  # type: ignore

    @classmethod
    async def close(cls) -> None:
        if cls._pool:
            await cls._pool.close()
            cls._pool = None
            cls._loop = None
            logger.info("Pool de DB cerrado.")

    @classmethod
    async def init_db(cls) -> None:
        """
        Inicializa extensiones y crea tablas + índices.
        NUEVO v3.0: agrega índices GIN para entities y relationships.
        """
        # 1. Asegurar extensiones usando una conexión cruda (sin codec de vector)
        db_host = config.POSTGRES_HOST
        if db_host == "localhost":
            db_host = "127.0.0.1"

        conn = await asyncpg.connect(
            user=config.POSTGRES_USER,
            password=config.POSTGRES_PASSWORD,
            database=config.POSTGRES_DB,
            host=db_host,
            port=config.POSTGRES_PORT,
        )
        try:
            for ext in ("vector", "uuid-ossp", "pg_trgm"):
                await conn.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}";')
        finally:
            await conn.close()

        # 2. Ahora sí podemos crear el pool con el codec de vector registrado
        pool = await cls.get_pool()
        expected_dims = config.EMBEDDING_DIMS

        async with pool.acquire() as conn:

            table_exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='chunks')"
            )

            if table_exists:
                current_dims = await conn.fetchval(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
                )
                if current_dims and current_dims != expected_dims:
                    logger.error(
                        "DIMENSIÓN MISMATCH: tabla tiene vector(%d), proveedor '%s' requiere vector(%d). "
                        "Ejecutá: bash scripts/reset_db.sh",
                        current_dims, config.LLM_PROVIDER, expected_dims
                    )
                    return

            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS documents (
                    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    title               TEXT NOT NULL,
                    filename            TEXT,
                    source_type         TEXT NOT NULL DEFAULT 'unknown',
                    graphiti_episode_id TEXT,
                    group_id            TEXT,
                    metadata            JSONB NOT NULL DEFAULT '{{}}',
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    content      TEXT NOT NULL,
                    embedding    vector({expected_dims}),
                    metadata     JSONB NOT NULL DEFAULT '{{}}',
                    chunk_index  INTEGER NOT NULL,
                    token_count  INTEGER DEFAULT 0,
                    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS generated_content (
                    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    run_id          UUID NOT NULL,
                    chunk_id        UUID REFERENCES chunks(id),
                    document_id     UUID REFERENCES documents(id),
                    content_type    TEXT NOT NULL,
                    content         JSONB NOT NULL,
                    qa_passed       BOOLEAN,
                    qa_reason       TEXT,
                    retry_count     INTEGER NOT NULL DEFAULT 0,
                    cost_usd        NUMERIC(10, 6),
                    model_used      TEXT,
                    tokens_in       INTEGER,
                    tokens_out      INTEGER,
                    notion_page_id  TEXT,
                    notion_url      TEXT,
                    notion_status   TEXT DEFAULT 'Pendiente',
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS weekly_runs (
                    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    run_date            DATE NOT NULL,
                    pieces_generated    INTEGER NOT NULL DEFAULT 0,
                    pieces_failed       INTEGER NOT NULL DEFAULT 0,
                    pieces_qa_passed    INTEGER NOT NULL DEFAULT 0,
                    pieces_qa_failed    INTEGER NOT NULL DEFAULT 0,
                    total_cost_usd      NUMERIC(10, 4),
                    status              TEXT NOT NULL DEFAULT 'running',
                    error_message       TEXT,
                    notion_run_url      TEXT,
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at        TIMESTAMPTZ
                );

                CREATE TABLE IF NOT EXISTS token_usage (
                    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    run_id       UUID,
                    operation    TEXT NOT NULL,
                    model        TEXT NOT NULL,
                    tokens_in    INTEGER NOT NULL DEFAULT 0,
                    tokens_out   INTEGER NOT NULL DEFAULT 0,
                    cost_usd     NUMERIC(10, 6) NOT NULL DEFAULT 0,
                    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            # Índices — existentes
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_chunks_embedding
                    ON chunks USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = {max(10, expected_dims // 50)});

                CREATE INDEX IF NOT EXISTS idx_chunks_topics
                    ON chunks USING GIN ((metadata->'topics'));
                CREATE INDEX IF NOT EXISTS idx_chunks_domain
                    ON chunks ((metadata->>'domain'));
                CREATE INDEX IF NOT EXISTS idx_chunks_content_level
                    ON chunks ((metadata->>'content_level'));
                CREATE INDEX IF NOT EXISTS idx_chunks_last_used
                    ON chunks ((metadata->>'last_used_at'));
                CREATE INDEX IF NOT EXISTS idx_chunks_document_id
                    ON chunks (document_id);
                CREATE INDEX IF NOT EXISTS idx_documents_content_hash
                    ON documents ((metadata->>'content_hash'));
                CREATE INDEX IF NOT EXISTS idx_generated_run_id
                    ON generated_content (run_id);
            """)

            # NUEVO v3.0: Índices para entities y relationships (estilo LightRAG)
            await conn.execute("""
                -- Índice GIN sobre el array de entities para búsqueda rápida
                -- Permite: WHERE metadata->'entities' @> '[{"name": "X"}]'
                CREATE INDEX IF NOT EXISTS idx_chunks_entities
                    ON chunks USING GIN ((metadata->'entities'));

                -- Índice GIN sobre relationships
                CREATE INDEX IF NOT EXISTS idx_chunks_relationships
                    ON chunks USING GIN ((metadata->'relationships'));
            """)

            # Función mark_chunk_used
            await conn.execute("""
                CREATE OR REPLACE FUNCTION mark_chunk_used(p_chunk_id UUID)
                RETURNS VOID AS $$
                BEGIN
                    UPDATE chunks
                    SET metadata = metadata || jsonb_build_object(
                        'used_count',   COALESCE((metadata->>'used_count')::INTEGER, 0) + 1,
                        'last_used_at', NOW()::TEXT
                    )
                    WHERE id = p_chunk_id;
                END;
                $$ LANGUAGE plpgsql;
            """)

        logger.info(
            "DB inicializada: provider=%s, embedding_dims=%d (con índices de entidades)",
            config.LLM_PROVIDER, expected_dims
        )

    @classmethod
    async def clear_database(cls) -> None:
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                DROP TABLE IF EXISTS token_usage CASCADE;
                DROP TABLE IF EXISTS generated_content CASCADE;
                DROP TABLE IF EXISTS weekly_runs CASCADE;
                DROP TABLE IF EXISTS chunks CASCADE;
                DROP TABLE IF EXISTS documents CASCADE;
            """)
            logger.info("Todas las tablas eliminadas. Ejecutar init_db() para recrear.")


async def _register_vector_codec(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "vector",
        encoder=lambda v: "[" + ",".join(str(x) for x in v) + "]",
        decoder=lambda s: [float(x) for x in s.strip("[]").split(",")],
        schema="public",
        format="text",
    )


@asynccontextmanager
async def get_db_connection():
    pool = await DatabasePool.get_pool()
    async with pool.acquire() as conn:
        yield conn


# =============================================================================
# HELPERS CRUD
# =============================================================================

async def document_exists_by_hash(content_hash: str) -> bool:
    async with get_db_connection() as conn:
        result = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM documents WHERE metadata->>'content_hash' = $1)",
            content_hash,
        )
        return bool(result)


async def insert_document(
    title: str,
    source: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    async with get_db_connection() as conn:
        doc_id = await conn.fetchval(
            """
            INSERT INTO documents (title, filename, source_type, metadata)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            title,
            source,
            (metadata or {}).get("source_type", "markdown"),
            json.dumps(metadata or {}),
        )
        return str(doc_id)


async def insert_chunks(
    doc_id: str,
    chunks: List[str],
    embeddings: List[List[float]],
    token_counts: Optional[List[int]] = None,
    metadata_list: Optional[List[Dict]] = None,
) -> None:
    """
    Inserta chunks con embeddings y metadata enriquecida (incluyendo entities).
    metadata_list debe tener la misma longitud que chunks.
    """
    if token_counts is None:
        token_counts = [0] * len(chunks)
    if metadata_list is None:
        metadata_list = [{}] * len(chunks)

    async with get_db_connection() as conn:
        await conn.executemany(
            """
            INSERT INTO chunks (document_id, content, embedding, chunk_index, token_count, metadata)
            VALUES ($1, $2, $3::vector, $4, $5, $6)
            """,
            [
                (
                    UUID(doc_id),
                    chunk,
                    embedding,
                    i,
                    token_counts[i],
                    json.dumps(metadata_list[i]),
                )
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
            ],
        )


async def mark_document_graph_ingested(doc_id: str, episode_id: str) -> None:
    async with get_db_connection() as conn:
        await conn.execute(
            """
            UPDATE documents
            SET graphiti_episode_id = $1,
                metadata = metadata || '{"graph_ingested": true}'::jsonb,
                updated_at = NOW()
            WHERE id = $2
            """,
            episode_id,
            UUID(doc_id),
        )


# =============================================================================
# HELPERS DE ANÁLISIS DE ENTIDADES — NUEVO v3.0
# =============================================================================

async def get_entity_stats(limit: int = 20) -> list[dict]:
    """
    Retorna las entidades más frecuentes en el corpus.
    Útil para el dashboard y para el Search Intent Generator.

    Returns:
        Lista de {name, type, chunk_count} ordenada por frecuencia descendente.
    """
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT
                e->>'name' AS entity_name,
                e->>'type' AS entity_type,
                COUNT(*) AS chunk_count
            FROM chunks,
                 jsonb_array_elements(metadata->'entities') AS e
            WHERE jsonb_array_length(metadata->'entities') > 0
              AND metadata->>'is_deleted' != 'true'
            GROUP BY e->>'name', e->>'type'
            ORDER BY chunk_count DESC
            LIMIT $1
            """,
            limit,
        )

    return [
        {
            "name": row["entity_name"],
            "type": row["entity_type"],
            "chunk_count": row["chunk_count"],
        }
        for row in rows
    ]


async def get_entity_co_occurrences(
    entity_name: str,
    limit: int = 10,
) -> list[dict]:
    """
    Retorna las entidades que co-ocurren más frecuentemente con la entidad dada.
    Útil para el Search Intent Generator: "si generamos sobre X, ¿qué más es relevante?"

    Returns:
        Lista de {name, type, co_occurrence_count}
    """
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            """
            WITH target_chunks AS (
                -- Chunks que contienen la entidad objetivo
                SELECT c.id
                FROM chunks c
                WHERE EXISTS (
                    SELECT 1 FROM jsonb_array_elements(c.metadata->'entities') AS e
                    WHERE lower(e->>'name') LIKE lower($1)
                )
            )
            SELECT
                e->>'name' AS entity_name,
                e->>'type' AS entity_type,
                COUNT(*) AS co_occurrence_count
            FROM chunks c
            JOIN target_chunks tc ON c.id = tc.id,
                 jsonb_array_elements(c.metadata->'entities') AS e
            WHERE lower(e->>'name') NOT LIKE lower($1)
              AND jsonb_array_length(c.metadata->'entities') > 0
            GROUP BY e->>'name', e->>'type'
            ORDER BY co_occurrence_count DESC
            LIMIT $2
            """,
            f"%{entity_name}%",
            limit,
        )

    return [
        {
            "name": row["entity_name"],
            "type": row["entity_type"],
            "co_occurrence_count": row["co_occurrence_count"],
        }
        for row in rows
    ]


async def get_document_summary() -> list[dict]:
    """Resumen de documentos para el dashboard (existente, mantenido)."""
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT
                d.id,
                d.title,
                d.filename AS source,
                d.created_at,
                COUNT(c.id) AS chunk_count,
                SUM(c.token_count) AS total_tokens,
                (d.metadata->>'graph_ingested')::boolean AS graph_ingested,
                (d.graphiti_episode_id IS NOT NULL) AS has_graphiti_node,
                jsonb_array_length(
                    COALESCE(
                        (SELECT jsonb_agg(DISTINCT e->>'name')
                         FROM chunks c2,
                              jsonb_array_elements(c2.metadata->'entities') AS e
                         WHERE c2.document_id = d.id),
                        '[]'::jsonb
                    )
                ) AS entity_count
            FROM documents d
            LEFT JOIN chunks c ON c.document_id = d.id
            GROUP BY d.id, d.title, d.filename, d.created_at, d.metadata, d.graphiti_episode_id
            ORDER BY d.created_at DESC
            """
        )

    return [dict(row) for row in rows]