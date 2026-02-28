import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from uuid import UUID

import asyncpg

from poc.config import config

logger = logging.getLogger(__name__)


# =============================================================================
# CONNECTION POOL
# =============================================================================

class DatabasePool:
    _pool: Optional[asyncpg.Pool] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    async def get_pool(cls) -> asyncpg.Pool:
        current_loop = asyncio.get_running_loop()

        # Resetear pool si el event loop cambió (común en testing y Streamlit)
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
            cls._pool = await asyncpg.create_pool(
                user=config.POSTGRES_USER,
                password=config.POSTGRES_PASSWORD,
                database=config.POSTGRES_DB,
                host=config.POSTGRES_HOST,
                port=config.POSTGRES_PORT,
                min_size=2,
                max_size=10,
                command_timeout=30,
                # Registrar codec para vectores pgvector
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
        Inicializa extensiones y crea tablas si no existen.

        CRÍTICO: La columna `embedding` se crea con las dimensiones configuradas
        en config.EMBEDDING_DIMS. Si cambiás de proveedor, ejecutá reset_db.sh.
        """
        pool = await cls.get_pool()
        expected_dims = config.EMBEDDING_DIMS

        async with pool.acquire() as conn:
            # Extensiones
            for ext in ("vector", "uuid-ossp", "pg_trgm"):
                await conn.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}";')

            # Verificar si chunks ya existe y tiene las dims correctas
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
                        "DIMENSIÓN MISMATCH: La tabla chunks tiene vector(%d) "
                        "pero el proveedor '%s' requiere vector(%d). "
                        "Ejecutá: bash scripts/reset_db.sh",
                        current_dims, config.LLM_PROVIDER, expected_dims
                    )
                    # No fallar — permitir que el sistema arranque (sin embeddings válidos)
                    return

            # Crear tablas
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

            # Índices (solo los que no existen)
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

            # Función para marcar chunks usados (diversity tracking)
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
            "DB inicializada: provider=%s, embedding_dims=%d",
            config.LLM_PROVIDER, expected_dims
        )

    @classmethod
    async def clear_database(cls) -> None:
        """
        Elimina todas las tablas. Útil al cambiar de proveedor (dims del vector).
        En producción usar scripts/reset_db.sh que también hace backup.
        """
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
    """Registra el codec para el tipo vector de pgvector."""
    await conn.set_type_codec(
        "vector",
        encoder=lambda v: "[" + ",".join(str(x) for x in v) + "]",
        decoder=lambda s: [float(x) for x in s.strip("[]").split(",")],
        schema="pg_catalog",
        format="text",
    )


@asynccontextmanager
async def get_db_connection():
    """Context manager para obtener una conexión del pool."""
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
    """Inserta un documento. Retorna el UUID del documento creado."""
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
    """Inserta chunks con sus embeddings en Postgres."""
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
                    "[" + ",".join(str(x) for x in embedding) + "]",
                    i,
                    token_counts[i],
                    json.dumps(metadata_list[i]),
                )
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
            ],
        )


async def mark_document_graph_ingested(doc_id: str, episode_id: str) -> None:
    """Marca un documento como ingresado en el grafo (Neo4j)."""
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