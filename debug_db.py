import asyncio
import json
from agent.db_utils import DatabasePool

async def check():
    await DatabasePool.init_db()
    pool = await DatabasePool.get_pool()
    rows = await pool.fetch("SELECT count(*) as count, (metadata->>'graph_ingested')::boolean IS TRUE as ingested FROM documents GROUP BY ingested")
    data = [dict(r) for r in rows]
    print(json.dumps(data, indent=2))
    await DatabasePool.close()

if __name__ == "__main__":
    asyncio.run(check())
