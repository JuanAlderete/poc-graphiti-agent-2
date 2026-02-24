import asyncio
import logging
from pathlib import Path
from typing import Optional

from agent.graph_utils import GraphClient, DEFAULT_GROUP_ID

logger = logging.getLogger(__name__)

# Directorio de documentos
DOCS_DIR = Path(__file__).parent.parent / "documents_to_index"


async def hydrate_graph(
    group_id: Optional[str] = DEFAULT_GROUP_ID,
    delay: float = 0.5,
    reset_flags: bool = False,
):
    """
    Read all markdown files and add them as episodes to the graph
    using GraphClient (singleton).

    Args:
        group_id: Logical group for all episodes. Uses DEFAULT_GROUP_ID
            so all documents are retrievable with a single query.
        delay: Seconds to sleep between episodes to avoid rate limits.
    """
    if reset_flags:
        # Resetear flag graph_ingested en todos los documentos
        from agent.db_utils import DatabasePool
        pool = await DatabasePool.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE documents SET metadata = metadata - 'graph_ingested', updated_at = NOW()"
            )
        logger.info("Reset graph_ingested flag on all documents.")
    
    if not DOCS_DIR.exists():
        logger.error("Documents directory not found: %s", DOCS_DIR)
        return

    md_files = sorted(DOCS_DIR.glob("*.md"))
    logger.info("Found %d markdown files to process", len(md_files))

    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8")
            doc_name = md_file.stem

            logger.info("Processing document: %s", doc_name)

            ep_uuid = await GraphClient.add_episode(
                content=content,
                source_reference=doc_name,
                source_description=f"Document from {md_file.name}",
                group_id=group_id,
            )

            # Sync metadata back to Postgres if the document exists there
            from agent.db_utils import get_db_connection, mark_document_graph_ingested
            async with get_db_connection() as conn:
                doc_record = await conn.fetchrow(
                    "SELECT id FROM documents WHERE source = $1 OR source = $2",
                    md_file.name, doc_name
                )
                if doc_record:
                    await mark_document_graph_ingested(str(doc_record["id"]), ep_uuid)
                    logger.info("Synced metadata to Postgres for: %s", doc_name)

            logger.info("Successfully added episode: %s (UUID: %s)", doc_name, ep_uuid)

            if delay > 0:
                await asyncio.sleep(delay)

        except Exception as e:
            logger.error("Error processing %s: %s", md_file.name, e)
            continue

    logger.info("Graph hydration completed")


async def verify_episodes():
    """
    Verify that all episodes were added correctly.
    Passes group_ids=None to retrieve ALL episodes regardless of group.
    """
    all_episodes = await GraphClient.get_all_episodes(group_ids=None)

    logger.info("Total episodes in graph: %d", len(all_episodes))

    for ep in all_episodes:
        logger.info("  - %s (group: %s)", ep["name"], ep.get("group_id", "N/A"))

    return all_episodes


async def main():
    """Main entry point."""
    # Ensure schema/indices exist
    await GraphClient.ensure_schema()

    try:
        # Hydrate the graph
        await hydrate_graph(group_id=DEFAULT_GROUP_ID)

        # Verify that ALL episodes are visible
        episodes = await verify_episodes()

        logger.info("Verification complete: %d episodes in graph", len(episodes))

    except Exception:
        logger.exception("Hydration failed")
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())