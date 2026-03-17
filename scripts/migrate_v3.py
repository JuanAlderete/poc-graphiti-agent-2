import asyncio
import asyncpg
import logging
from poc.config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def migrate():
    # Usar 127.0.0.1 para evitar rollos de IPv6 en Windows
    host = config.POSTGRES_HOST
    if host == "localhost":
        host = "127.0.0.1"
        
    logger.info(f"Conectando a {host}:{config.POSTGRES_PORT}...")
    
    conn = await asyncpg.connect(
        user=config.POSTGRES_USER,
        password=config.POSTGRES_PASSWORD,
        database=config.POSTGRES_DB,
        host=host,
        port=config.POSTGRES_PORT,
    )
    
    try:
        # 1. Obtener columnas actuales
        columns = await conn.fetch("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'documents'
        """)
        column_names = [c['column_name'] for c in columns]
        logger.info(f"Columnas detectadas en 'documents': {column_names}")
        
        # 2. Renombrar source -> filename
        if 'source' in column_names and 'filename' not in column_names:
            logger.info("Renombrando 'source' -> 'filename'...")
            await conn.execute("ALTER TABLE documents RENAME COLUMN source TO filename;")
        
        # 3. Agregar missing columns
        if 'source_type' not in column_names:
            logger.info("Agregando 'source_type'...")
            await conn.execute("ALTER TABLE documents ADD COLUMN source_type TEXT DEFAULT 'unknown';")
            
        if 'group_id' not in column_names:
            logger.info("Agregando 'group_id'...")
            await conn.execute("ALTER TABLE documents ADD COLUMN group_id TEXT;")
            
        # 4. Verificar chunks (por si acaso)
        columns_chunks = await conn.fetch("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'chunks'
        """)
        chunks_column_names = [c['column_name'] for c in columns_chunks]
        
        if 'token_count' not in chunks_column_names:
            logger.info("Agregando 'token_count' a 'chunks'...")
            await conn.execute("ALTER TABLE chunks ADD COLUMN token_count INTEGER DEFAULT 0;")

        logger.info("✅ Migración completada con éxito.")
        
    except Exception as e:
        logger.error(f"❌ Error durante la migración: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate())
