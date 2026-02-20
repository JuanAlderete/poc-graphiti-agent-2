import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import asyncpg

from agent.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pool management
# ---------------------------------------------------------------------------

class DatabasePool:
    _pool: Optional[asyncpg.Pool] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    async def get_pool(cls) -> asyncpg.Pool:
        current_loop = asyncio.get_running_loop()

        if cls._pool is not None:
            loop_changed = cls._loop is not current_loop
            loop_closed = cls._loop is None or cls._loop.is_closed()
            if loop_changed or loop_closed:
                logger.warning("Event loop changed or closed — resetting DB pool.")
                # Attempt a clean close; ignore errors (old loop may be gone)
                try:
                    await cls._pool.close()
                except Exception:
                    pass
                cls._pool = None
                cls._loop = None

        if cls._pool is None:
            try:
                cls._pool = await asyncpg.create_pool(
                    user=settings.POSTGRES_USER,
                    password=settings.POSTGRES_PASSWORD,
                    database=settings.POSTGRES_DB,
                    host=settings.POSTGRES_HOST,
                    port=settings.POSTGRES_PORT,
                    min_size=2,
                    max_size=10,
                    command_timeout=30,
                )
                cls._loop = current_loop
                logger.info("Database connection pool created (min=2, max=10).")
            except Exception:
                logger.exception("Failed to create database pool")
                raise

        return cls._pool  # type: ignore[return-value]

    @classmethod
    async def close(cls) -> None:
        if cls._pool:
            await cls._pool.close()
            cls._pool = None
            cls._loop = None

    @classmethod
    async def clear_database(cls) -> None:
        """Truncates documents and chunks tables (CASCADE)."""
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("TRUNCATE TABLE chunks, documents CASCADE;")
            logger.info("Cleared Postgres tables: documents, chunks.")

    @classmethod
    async def init_db(cls) -> None:
        """
        Ensures required extensions exist and applies schema.sql if the
        chunks table is missing.
        """
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            # Extensions
            for ext in ("vector", "uuid-ossp", "pg_trgm"):
                await conn.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}";')
            logger.info("Database extensions ensured.")

            # Determine vector dimension
            expected_dim = 768 if (
                "gemini" in settings.LLM_PROVIDER.lower()
                or "004" in settings.EMBEDDING_MODEL
            ) else 1536
            logger.info("Expected embedding dimension: %d", expected_dim)

            table_exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'chunks'
                )
                """
            )

            if not table_exists:
                try:
                    with open("sql/schema.sql", encoding="utf-8") as fh:
                        schema_sql = fh.read()
                    if expected_dim != 1536:
                        schema_sql = schema_sql.replace("vector(1536)", f"vector({expected_dim})")
                        logger.info("Adjusted schema to vector(%d)", expected_dim)
                    await conn.execute(schema_sql)
                    logger.info("Database schema applied from sql/schema.sql.")
                except Exception:
                    logger.exception("Failed to apply schema")
                    raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@asynccontextmanager
async def get_db_connection():
    pool = await DatabasePool.get_pool()
    async with pool.acquire() as conn:
        yield conn


def _fmt_vec(embedding: List[float]) -> str:
    """Convert a Python float list to the pgvector literal format '[1.0,2.0,...]'."""
    return "[" + ",".join(str(v) for v in embedding) + "]"


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

async def insert_document(
    title: str,
    source: str,
    content: str,
    metadata: dict | None = None,
) -> str:
    """Inserts a document record and returns its UUID as a string."""
    async with get_db_connection() as conn:
        doc_id = await conn.fetchval(
            """
            INSERT INTO documents (title, source, content, metadata)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            title,
            source,
            content,
            json.dumps(metadata or {}),
        )
        return str(doc_id)


async def insert_chunks(
    doc_id: str,
    chunks: List[str],
    embeddings: List[List[float]],
    start_index: int = 0,
) -> None:
    """
    Inserts chunks with their embeddings for a given document.

    FIXED: uses _fmt_vec() consistently and passes metadata as a JSON string
    rather than json.dumps({}) inside a tuple (minor but cleaner).
    """
    async with get_db_connection() as conn:
        chunk_data = [
            (
                doc_id,
                chunk_text,
                _fmt_vec(embedding),
                start_index + i,
                "{}",  # metadata JSONB — empty object literal
            )
            for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings))
        ]
        await conn.executemany(
            """
            INSERT INTO chunks (document_id, content, embedding, chunk_index, metadata)
            VALUES ($1::uuid, $2, $3::vector, $4, $5::jsonb)
            """,
            chunk_data,
        )


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

async def vector_search(
    embedding: List[float],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Cosine-similarity vector search against the chunks table."""
    limit = max(1, limit)
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.id,
                c.content,
                c.metadata,
                d.title,
                d.source,
                1 - (c.embedding <=> $1::vector) AS score
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            ORDER BY c.embedding <=> $1::vector
            LIMIT $2
            """,
            _fmt_vec(embedding),
            limit,
        )
        return [dict(row) for row in rows]


async def hybrid_search(
    text_query: str,
    embedding: List[float],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Hybrid RRF search using the stored procedure defined in schema.sql."""
    limit = max(1, limit)
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            "SELECT * FROM hybrid_search($1::vector, $2, $3)",
            _fmt_vec(embedding),
            text_query,
            limit,
        )
        return [dict(row) for row in rows]


async def get_all_documents() -> List[Dict[str, Any]]:
    """Fetches all documents (id, title, source, content, metadata) from the DB."""
    async with get_db_connection() as conn:
        rows = await conn.fetch("SELECT id, title, source, content, metadata FROM documents")
        return [dict(row) for row in rows]