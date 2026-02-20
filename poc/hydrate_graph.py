
import asyncio
import logging
import time
from typing import List, Dict, Any

from agent.db_utils import DatabasePool, get_all_documents
from agent.graph_utils import GraphClient
from poc.token_tracker import tracker
from agent.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

async def hydrate_graph():
    """
    Reads documents from Postgres and pushes them to Graphiti.
    Simulates "Phase 2" migration without re-ingesting original files.
    """
    logger.info("Initializing DB pool...")
    await DatabasePool.init_db()
    
    # 1. Fetch from Postgres
    logger.info("Fetching documents from Postgres...")
    docs = await get_all_documents()
    
    if not docs:
        logger.warning("No documents found in Postgres. Run ingestion first (Phase 1).")
        return

    logger.info(f"Found {len(docs)} documents. Starting graph hydration...")

    # 2. Push to Graphiti
    # Using semaphore to limit concurrency and avoid rate limits
    concurrency = 3
    sem = asyncio.Semaphore(concurrency)
    
    total_cost = 0.0
    start_time = time.time()
    
    async def _process(doc: Dict[str, Any]):
        async with sem:
            # We use the document content and title/source
            raw_content = doc["content"]
            source = doc["title"] or "unknown_doc"
            
            # Phase 1.5: Metadata Injection
            # db_utils.get_all_documents returns 'source' column as 'source' key? 
            # checks db_utils: SELECT id, title, source, content FROM documents
            # And metadata is stored in 'metadata' column? The query in get_all_documents didn't fetch metadata!
            # I must update get_all_documents first or just accept I need to fetch it.
            # Wait, I missed updating get_all_documents to fetch metadata column in previous step.
            # I will fix this right here by updating the query in db_utils in the next step or 
            # I can just proceed if I fix db_utils. 
            # Let's Assume I fix get_all_documents to return metadata.
            
            # For now, let's assume doc has 'metadata' key if I fix the query.
            # ...
            # Actually, I should check if doc has metadata.
            # doc is a dict from row.
            
            doc_metadata = doc.get("metadata", {})
            if isinstance(doc_metadata, str):
                import json
                try:
                    doc_metadata = json.loads(doc_metadata)
                except:
                    doc_metadata = {}
            
            # Format context string
            context_str = ""
            if doc_metadata:
                context_parts = [f"{k.capitalize()}: {v}" for k, v in doc_metadata.items() if k not in ["filename", "source_type"]]
                if context_parts:
                    context_str = f"[METADATA]\n" + "\n".join(context_parts) + "\n\n[CONTENT]\n"
            
            final_content = context_str + raw_content

            try:
                await GraphClient.add_episode(final_content, source)
            except Exception as e:
                logger.error(f"Failed to hydrate {source}: {e}")

    # Ensure schema exists (indices)
    await GraphClient.ensure_schema()
    
    # Run in parallel
    await asyncio.gather(*(_process(doc) for doc in docs))
    
    elapsed = time.time() - start_time
    
    # Calculate Total Cost from Tracker
    # We can iterate over all operations in tracker to sum up 'graph_ingestion' type
    # But tracker._operations clears after end_operation.
    # So we rely on the logs printed by GraphClient.
    
    logger.info(f"Hydration complete in {elapsed:.2f}s.")
    logger.info("Check logs/graphiti_ingest.log (if configured) or stdout for individual costs.")
    logger.info("NOTE: This phase uses LLMs (gpt-5-mini/gpt-4o-mini) and incurs costs.")

if __name__ == "__main__":
    asyncio.run(hydrate_graph())
