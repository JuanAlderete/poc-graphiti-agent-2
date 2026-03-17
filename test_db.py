import asyncio
import asyncpg
from poc.config import config

async def test_connection():
    print(f"Testing connection to {config.POSTGRES_HOST}:{config.POSTGRES_PORT}")
    print(f"User: {config.POSTGRES_USER}")
    print(f"Database: {config.POSTGRES_DB}")
    
    try:
        conn = await asyncpg.connect(
            user=config.POSTGRES_USER,
            password=config.POSTGRES_PASSWORD,
            database=config.POSTGRES_DB,
            host=config.POSTGRES_HOST,
            port=config.POSTGRES_PORT,
            timeout=5
        )
        print("✅ Connection successful!")
        
        columns = await conn.fetch("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'documents'
        """)
        print("\nColumns in 'documents' table:")
        for col in columns:
            print(f"- {col['column_name']} ({col['data_type']})")

        columns_chunks = await conn.fetch("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'chunks'
        """)
        print("\nColumns in 'chunks' table:")
        for col in columns_chunks:
            print(f"- {col['column_name']} ({col['data_type']})")
            
        await conn.close()
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
