import asyncio
import logging
import os
import time
from typing import List

from agent.config import settings
from agent.db_utils import DatabasePool, insert_chunks, insert_document
from agent.graph_utils import GraphClient
from ingestion.chunker import SemanticChunker
from ingestion.embedder import get_embedder
from poc.logging_utils import ingestion_logger
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)

class DocumentIngestionPipeline:
    def __init__(self) -> None:
        self.chunker = SemanticChunker()
        # FIXED: use module-level singleton instead of creating a new client per pipeline
        self.embedder = get_embedder()

    async def ingest_file(self, file_path: str, skip_graphiti: bool = False) -> float:
        """
        Ingests a single file.  Returns the total estimated cost in USD.
        """
        start_time = time.time()
        filename = os.path.basename(file_path)
        op_id = f"ingest_{filename}_{int(start_time)}"

        tracker.start_operation(op_id, "ingestion")
        cost = 0.0

        try:
            with open(file_path, encoding="utf-8") as fh:
                content = fh.read()

            # 1. Extract Frontmatter
            metadata, content_body = self._parse_frontmatter(content)
            
            # Merge with system metadata
            doc_metadata = {
                "source_type": "markdown",
                "filename": filename,
                **metadata
            }

            # 2. Chunk (body only)
            chunks = self.chunker.chunk(content_body)

            # 3. Embed
            embeddings, embed_tokens = await self.embedder.generate_embeddings_batch(chunks)
            tracker.record_usage(op_id, embed_tokens, 0, settings.EMBEDDING_MODEL, "embedding_api")

            # 4. Persist to Postgres
            doc_id = await insert_document(
                title=metadata.get("title", filename), # Use title from frontmatter if available
                source=filename,
                content=content_body, # Store body without frontmatter? Or full content? 
                # Decision: Store full content? No, strictly better to store body if we extracted metadata.
                # Actually, for reproducibility, maybe keep full content? 
                # But for RAG, we usually want the body.
                # Let's store content_body to avoid re-indexing headers.
                # But wait, Phase 2 hydration might need context. 
                # We are storing metadata in the 'metadata' column, so we don't need it in 'content'.
                metadata=doc_metadata,
            )
            await insert_chunks(doc_id, chunks, embeddings)

            # 5. Graph ingestion (optional)
            if not skip_graphiti:
                # Pass the whole document (body) for richer entity context
                # We can inject metadata string here if we want immediate graph benefit in Phase 1 (if not skipping)
                # But for now, just body.
                await GraphClient.add_episode(content_body, filename)

            latency = time.time() - start_time
            metrics = tracker.end_operation(op_id)
            cost = metrics.cost_usd if metrics else 0.0

            ingestion_logger.log_row(
                {
                    "episodio_id": op_id,
                    "timestamp": start_time,
                    "source_type": "markdown",
                    "nombre_archivo": filename,
                    "longitud_palabras": len(content_body.split()),
                    "chunks_creados": len(chunks),
                    "embeddings_tokens": embed_tokens,
                    "costo_total_usd": cost,
                    "tiempo_seg": latency,
                }
            )

            logger.info("Ingested %s: cost=$%.4f, time=%.2fs", filename, cost, latency)
            return cost

        except Exception:
            logger.exception("Failed to ingest %s", file_path)
            raise
        finally:
            # Ensure tracker entry is always cleaned up even on unexpected errors
            tracker.end_operation(op_id)

    def _parse_frontmatter(self, text: str) -> tuple[dict, str]:
        """
        Extracts YAML frontmatter from text.
        Returns (metadata_dict, content_body).
        SIMPLE IMPLEMENTATION: Looks for --- at start.
        """
        import yaml
        
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}, text
            
        fontmatter = []
        body = []
        in_frontmatter = True
        
        for i, line in enumerate(lines[1:], 1):
            if in_frontmatter:
                if line.strip() == "---":
                    in_frontmatter = False
                    continue
                fontmatter.append(line)
            else:
                body.append(line)
        
        try:
            metadata = yaml.safe_load("\n".join(fontmatter)) or {}
            if not isinstance(metadata, dict):
                 metadata = {}
            return metadata, "\n".join(body)
        except Exception as e:
            logger.warning(f"Failed to parse frontmatter: {e}")
            return {}, text


async def ingest_directory(directory: str, skip_graphiti: bool = False) -> None:
    """
    Ingests all Markdown files in *directory* with bounded concurrency.
    """
    pipeline = DocumentIngestionPipeline()
    await DatabasePool.init_db()

    files = sorted(
        [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(".md")]
    )

    if not files:
        logger.warning("No .md files found in '%s'.", directory)
        return

    # FIXED: tighter concurrency for Graphiti to avoid LLM rate-limit spikes
    concurrency = 3 if not skip_graphiti else 5
    sem = asyncio.Semaphore(concurrency)
    total_cost = 0.0
    t0 = time.time()

    async def _bound(f: str) -> float:
        async with sem:
            return await pipeline.ingest_file(f, skip_graphiti=skip_graphiti)

    mode = "Postgres Only" if skip_graphiti else "Postgres + Graphiti"
    logger.info("Ingesting %d files [%s, concurrency=%d]…", len(files), mode, concurrency)

    results = await asyncio.gather(*(_bound(f) for f in files), return_exceptions=True)

    for r in results:
        if isinstance(r, Exception):
            logger.error("Ingestion error: %s", r)
        else:
            total_cost += r  # type: ignore[operator]

    elapsed = time.time() - t0
    logger.info(
        "Ingestion complete: %d files in %.1fs — total estimated cost: $%.4f",
        len(files),
        elapsed,
        total_cost,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=str, required=True, help="Directory to ingest")
    parser.add_argument("--skip-graphiti", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(ingest_directory(args.dir, skip_graphiti=args.skip_graphiti))