import asyncio
from agent.db_utils import DatabasePool, insert_document
import hashlib

async def test_insert_list():
    await DatabasePool.init_db()
    content = "Hello list test"
    
    # Generate dummy doc
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    doc_id = await insert_document(
        title="test_list.md", source="test_list.md", content=content,
        metadata={"filename": "test_list.md", "content_hash": content_hash}
    )
    
    print(f"Doc created: {doc_id}")
    
    # We will pass the list directly, no string concatenation!
    embeddings = [[0.01] * 768]
    chunks = [content]
    
    pool = await DatabasePool.get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.executemany(
                """
                INSERT INTO chunks (document_id, content, chunk_index, token_count, metadata, embedding)
                VALUES ($1, $2, $3, $4, $5, $6::vector)
                """,
                [
                    (
                        doc_id,
                        chunks[i],
                        i,
                        10,
                        '{}',
                        embeddings[i]  # EXACT NATIVE LIST HERE!!!
                    )
                    for i in range(len(chunks))
                ]
            )
            print("SUCCESS! Inserted float[] directly to vector!")
        except Exception as e:
            print("Failed:", type(e).__name__, str(e)[:100])

if __name__ == "__main__":
    asyncio.run(test_insert_list())
