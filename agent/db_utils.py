import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import asyncpg

from agent.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------------

class DatabasePool:
    _pool: Optional[asyncpg.Pool] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    async def get_pool(cls) -> asyncpg.Pool:
        current_loop = asyncio.get_running_loop()
        if cls._pool is not None:
            if cls._loop is not current_loop or (cls._loop and cls._loop.is_closed()):
                logger.warning("Event loop changed — resetting DB pool.")
                try:
                    await cls._pool.close()
                except Exception:
                    pass
                cls._pool = None
                cls._loop = None

        if cls._pool is None:
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
            logger.info("DB pool created (min=2, max=10).")

        return cls._pool  # type: ignore[return-value]

    @classmethod
    async def close(cls) -> None:
        if cls._pool:
            await cls._pool.close()
            cls._pool = None
            cls._loop = None

    @classmethod
    async def clear_database(cls) -> None:
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            # DROP instead of TRUNCATE so init_db() can recreate with correct vector dimension
            await conn.execute("DROP TABLE IF EXISTS chunks CASCADE;")
            await conn.execute("DROP TABLE IF EXISTS documents CASCADE;")
            await conn.execute("DROP VIEW IF EXISTS v_document_summary CASCADE;")
            logger.info("Dropped documents + chunks tables (will recreate on next init).")

    @classmethod
    async def init_db(cls) -> None:
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            for ext in ("vector", "uuid-ossp", "pg_trgm"):
                await conn.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}";')

            expected_dim = 768 if (
                "gemini" in settings.LLM_PROVIDER.lower()
                or "ollama" in settings.LLM_PROVIDER.lower()
                or "004" in settings.EMBEDDING_MODEL
            ) else 1536

            table_exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='chunks')"
            )

            # If table exists, check if vector dimension matches current provider
            if table_exists:
                current_dim = await conn.fetchval(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
                )
                if current_dim and current_dim != expected_dim:
                    logger.warning(
                        "Vector dimension mismatch: table has %d, provider needs %d. "
                        "Recreating schema...", current_dim, expected_dim
                    )
                    await conn.execute("DROP TABLE IF EXISTS chunks CASCADE;")
                    await conn.execute("DROP TABLE IF EXISTS documents CASCADE;")
                    await conn.execute("DROP VIEW IF EXISTS v_document_summary CASCADE;")
                    table_exists = False

            if not table_exists:
                with open("sql/schema.sql", encoding="utf-8") as fh:
                    sql = fh.read()
                if expected_dim != 1536:
                    sql = sql.replace("vector(1536)", f"vector({expected_dim})")
                await conn.execute(sql)
                logger.info("Schema applied (dim=%d).", expected_dim)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@asynccontextmanager
async def get_db_connection():
    pool = await DatabasePool.get_pool()
    async with pool.acquire() as conn:
        yield conn


def _fmt_vec(embedding: List[float]) -> str:
    return "[" + ",".join(str(v) for v in embedding) + "]"


# ---------------------------------------------------------------------------
# Deduplicación
# ---------------------------------------------------------------------------

async def document_exists_by_hash(content_hash: str) -> bool:
    """
    Retorna True si ya existe un documento con ese hash de contenido.
    Usa el campo metadata->>'content_hash' guardado en ingesta.
    Evita re-ingestar el mismo archivo al re-ejecutar el script.
    """
    async with get_db_connection() as conn:
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM documents WHERE metadata->>'content_hash' = $1)",
            content_hash,
        )
        return bool(exists)


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

async def insert_document(
    title: str,
    source: str,
    content: str,
    metadata: dict | None = None,
    graphiti_episode_id: str | None = None,
) -> str:
    async with get_db_connection() as conn:
        doc_id = await conn.fetchval(
            "INSERT INTO documents (title, source, content, metadata, graphiti_episode_id) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            title, source, content, json.dumps(metadata or {}), graphiti_episode_id,
        )
        return str(doc_id)


async def insert_chunks(
    doc_id: str,
    chunks: List[str],
    embeddings: List[List[float]],
    start_index: int = 0,
    chunk_metas: List[Dict[str, Any]] | None = None,
    token_counts: List[int] | None = None,
) -> None:
    """
    Inserta chunks con embeddings.
    `chunk_metas`: lista de dicts (uno por chunk) con metadata enriquecida.
    `token_counts`: lista de integers con el conteo de tokens por chunk.
    """
    metas = chunk_metas or [{}] * len(chunks)
    async with get_db_connection() as conn:
        data = [
            (
                doc_id,
                chunk_text,
                _fmt_vec(embedding),
                start_index + i,
                json.dumps(metas[i] if i < len(metas) else {}),
                token_counts[i] if token_counts and i < len(token_counts) else 0,
            )
            for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings))
        ]
        await conn.executemany(
            "INSERT INTO chunks (document_id, content, embedding, chunk_index, metadata, token_count) "
            "VALUES ($1::uuid, $2, $3::vector, $4, $5::jsonb, $6)",
            data,
        )


# ---------------------------------------------------------------------------
# Read helpers para hydrate_graph.py
# ---------------------------------------------------------------------------

async def get_all_documents(
    limit: int = 1000,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Devuelve todos los documentos de Postgres para hydrate_graph.py.
    Incluye metadata (JSONB parseado) — contiene detected_people,
    detected_companies y graphiti_ready_context pre-calculados.

    Soporta paginación para datasets grandes.
    """
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, source, content, metadata, created_at
            FROM documents
            ORDER BY created_at ASC
            LIMIT $1 OFFSET $2
            """,
            limit, offset,
        )
        result = []
        for row in rows:
            d = dict(row)
            # Normaliza metadata: puede venir como str o dict
            raw_meta = d.get("metadata", {})
            if isinstance(raw_meta, str):
                try:
                    d["metadata"] = json.loads(raw_meta)
                except Exception:
                    d["metadata"] = {}
            d["id"] = str(d["id"])
            result.append(d)
        return result


async def get_documents_missing_from_graph(limit: int = 500) -> List[Dict[str, Any]]:
    """
    Retorna documentos que NO han sido hidratados al grafo todavía.
    Usa el flag metadata->>'graph_ingested' para llevar el control.

    hydrate_graph.py puede llamar a esta función para reanudar una
    hidratación interrumpida sin reprocesar todo.
    """
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, source, content, metadata
            FROM documents
            WHERE (metadata->>'graph_ingested')::boolean IS NOT TRUE
            ORDER BY created_at ASC
            LIMIT $1
            """,
            limit,
        )
        result = []
        for row in rows:
            d = dict(row)
            raw_meta = d.get("metadata", {})
            if isinstance(raw_meta, str):
                try:
                    d["metadata"] = json.loads(raw_meta)
                except Exception:
                    d["metadata"] = {}
            d["id"] = str(d["id"])
            result.append(d)
        return result


async def mark_document_graph_ingested(doc_id: str, graphiti_episode_id: str | None = None) -> None:
    """
    Marca un documento como ya hidratado en el grafo.
    Permite reanudar hydrate_graph.py sin reprocesar docs ya hechos.
    """
    async with get_db_connection() as conn:
        await conn.execute(
            """
            UPDATE documents
            SET metadata = metadata || '{"graph_ingested": true}'::jsonb,
                graphiti_episode_id = COALESCE($2, graphiti_episode_id),
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            doc_id, graphiti_episode_id,
        )


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

async def vector_search(
    embedding: List[float],
    limit: int = 5,
) -> List[Dict[str, Any]]:
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
            _fmt_vec(embedding), limit,
        )
        return [dict(row) for row in rows]


async def hybrid_search(
    text_query: str,
    embedding: List[float],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    limit = max(1, limit)
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            "SELECT * FROM hybrid_search($1::vector, $2, $3)",
            _fmt_vec(embedding), text_query, limit,
        )
        return [dict(row) for row in rows]


async def get_document_summary() -> List[Dict[str, Any]]:
    """
    Returns a summary of all documents in the database (from v_document_summary view).
    """
    async with get_db_connection() as conn:
        try:
            records = await conn.fetch("SELECT * FROM v_document_summary ORDER BY created_at DESC")
            # Convert asyncpg UUID objects to strings for Streamlit/Arrow compatibility
            result = []
            for r in records:
                d = dict(r)
                if 'id' in d:
                    d['id'] = str(d['id'])
                if 'document_id' in d:
                    d['document_id'] = str(d['document_id'])
                result.append(d)
            return result
        except Exception as e:
            logger.error(f"Error fetching document summary: {e}")
            return []


async def get_chunks_by_document_source(
    source_name: str,
    limit: int = 5,
) -> list[dict]:
    """
    Retorna chunks de documentos cuyo `source` coincide con source_name.
    Usado por RetrievalEngine para buscar chunks de un episodio específico del grafo.

    Args:
        source_name: Nombre del documento/episodio (ej: 'alex.md' o 'alex').
    """
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT c.content, c.metadata, d.title, d.source, d.graphiti_episode_id,
                   c.chunk_index
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE d.source ILIKE $1 OR d.source ILIKE $2 OR d.title ILIKE $1
            ORDER BY c.chunk_index ASC
            LIMIT $3
            """,
            f"%{source_name}%",
            f"{source_name}%",
            limit,
        )
        return [dict(row) for row in rows]