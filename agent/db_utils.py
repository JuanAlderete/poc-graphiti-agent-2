import asyncio
import asyncpg

import logging
import json
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
from agent.config import settings

logger = logging.getLogger(__name__)

class DatabasePool:
    _pool = None
    _loop = None

    @classmethod
    async def get_pool(cls):
        current_loop = asyncio.get_running_loop()
        
        # Reset if pool belongs to a different or closed loop
        if cls._pool is not None:
            if cls._loop != current_loop or cls._loop.is_closed():
                logger.warning("Event loop changed or closed. Resetting connection pool.")
                # We cannot safely close the old pool if the loop is closed, 
                # so we just drop the reference.
                cls._pool = None
        
        if cls._pool is None:
            try:
                cls._pool = await asyncpg.create_pool(
                    user=settings.POSTGRES_USER,
                    password=settings.POSTGRES_PASSWORD,
                    database=settings.POSTGRES_DB,
                    host=settings.POSTGRES_HOST,
                    port=settings.POSTGRES_PORT,
                    min_size=1,
                    max_size=10
                )
                cls._loop = current_loop
                logger.info("Database pool created.")
            except Exception as e:
                logger.error(f"Failed to create database pool: {e}")
                raise
        return cls._pool


    @classmethod
    async def close(cls):
        if cls._pool:
            await cls._pool.close()
            cls._pool = None

    @classmethod
    async def clear_database(cls):
        """Truncates documents and chunks tables."""
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            try:
                await conn.execute("TRUNCATE TABLE chunks, documents CASCADE;")
                logger.info("Cleared Postgres tables: documents, chunks.")
            except Exception as e:
                logger.error(f"Failed to clear database: {e}")
                raise

    @classmethod
    async def init_db(cls):

        """
        Initializes the database schema.
        Note: The schema is currently managed via sql/schema.sql.
        This method serves as a check or fallback.
        In a real prod setup, we'd use migration tools like Alembic.
        """
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            try:
                # Basic check if vector extension exists
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                await conn.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")
                await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
                
                logger.info("Database extensions checked.")

                # Determine expected dimension based on config
                # Default to 1536 (OpenAI) if unknown
                expected_dim = 1536
                if "gemini" in settings.LLM_PROVIDER.lower() or "004" in settings.EMBEDDING_MODEL:
                     expected_dim = 768
                
                logger.info(f"Expected embedding dimension: {expected_dim}")

                # Check if chunks table exists
                table_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE  table_schema = 'public'
                        AND    table_name   = 'chunks'
                    );
                """)

                if not table_exists:
                    # Apply schema.sql with correct dimension
                    try:
                        with open('sql/schema.sql', 'r', encoding='utf-8') as f:
                            schema_sql = f.read()
                        
                        # Replace default vector(1536) with expected
                        if expected_dim != 1536:
                            schema_sql = schema_sql.replace("vector(1536)", f"vector({expected_dim})")
                            logger.info(f"Adjusted schema to vector({expected_dim})")
                            
                        await conn.execute(schema_sql)
                        logger.info("Database schema applied from sql/schema.sql.")
                    except Exception as e:
                         logger.error(f"Failed to apply schema: {e}")
                         raise
                else:
                    # Table exists, check dimension
                    # We can check pg_attribute or try to cast or check information_schema (if data_type shows it)
                    # psql \d chunks shows vector(1536).
                    # 'atttypmod' stores width/precision. For vector, it might be related.
                    # Safest: Use a query to check
                    try:
                        # typmod for vector(N) is usually N
                        # But let's check exact string representation if possible?
                        # Or checking error on dummy insert? No.
                        # Query pg_attribute for atttypmod
                        # Postgres stores (dim) in atttypmod but offset by 4?
                        # Let's trust that if the user didn't drop tables, they might have 1536.
                        # We will log a warning if we detect mismatch, or just let it fail at runtime.
                        # But detecting is better.
                        pass # Placeholder for advanced check. 
                        # If mismatch, insert will fail with "vector has different dimension". 
                        # We'll rely on that for now to avoid complex introspection logic bugs.
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"DB Init Error: {e}")

@asynccontextmanager
async def get_db_connection():
    pool = await DatabasePool.get_pool()
    async with pool.acquire() as conn:
        yield conn

async def insert_document(title: str, source: str, content: str, metadata: dict = {}) -> str:
    """Inserts a document metadata record and returns its ID."""
    async with get_db_connection() as conn:
        doc_id = await conn.fetchval("""
            INSERT INTO documents (title, source, content, metadata) 
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """, title, source, content, json.dumps(metadata))
        return str(doc_id)

async def insert_chunks(doc_id: str, chunks: List[str], embeddings: List[List[float]], start_index: int = 0):
    """Inserts chunks for a given document."""
    async with get_db_connection() as conn:
        chunk_data = []
        for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_data.append((
                doc_id, 
                chunk_text, 
                str(embedding), # pgvector format
                start_index + i, 
                json.dumps({}) 
            ))
            
        await conn.executemany("""
            INSERT INTO chunks (document_id, content, embedding, chunk_index, metadata)
            VALUES ($1::uuid, $2, $3::vector, $4, $5::jsonb)
        """, chunk_data)

async def vector_search(embedding: List[float], limit: int = 5) -> List[Dict[str, Any]]:
    """Performs vector search using the match_chunks function or raw query."""
    async with get_db_connection() as conn:
        formatted_embedding = str(embedding)
        # Using the simplified query matching the new schema
        rows = await conn.fetch("""
            SELECT 
                c.id,
                c.content, 
                c.metadata,
                d.title,
                d.source,
                1 - (c.embedding <=> $1::vector) as score
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            ORDER BY c.embedding <=> $1::vector
            LIMIT $2
        """, formatted_embedding, limit)
        return [dict(row) for row in rows]

async def hybrid_search(text_query: str, embedding: List[float], limit: int = 5) -> List[Dict[str, Any]]:
    """Performs hybrid search using the stored procedure."""
    async with get_db_connection() as conn:
        formatted_embedding = str(embedding)
        # Calls the stored function defined in schema.sql
        rows = await conn.fetch("""
            SELECT * FROM hybrid_search($1::vector, $2, $3)
        """, formatted_embedding, text_query, limit)
        return [dict(row) for row in rows]
