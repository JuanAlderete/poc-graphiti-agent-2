import asyncio
import os
import time
import logging
from typing import List
from agent.db_utils import DatabasePool, insert_document, insert_chunks

from agent.graph_utils import GraphClient
from ingestion.chunker import SemanticChunker
from ingestion.embedder import EmbeddingGenerator
from poc.token_tracker import tracker
from poc.logging_utils import ingestion_logger
from agent.config import settings

logger = logging.getLogger(__name__)

class DocumentIngestionPipeline:
    def __init__(self):
        self.chunker = SemanticChunker()
        self.embedder = EmbeddingGenerator()

    async def ingest_file(self, file_path: str, skip_graphiti: bool = False):
        """
        Ingests a single file into Postgres and optionally Graphiti.
        """
        start_time = time.time()
        filename = os.path.basename(file_path)
        op_id = f"ingest_{filename}_{int(start_time)}"
        
        tracker.start_operation(op_id, "ingestion")
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # 1. Chunking (No tokens, just CPU)
            chunks = self.chunker.chunk(content)
            
            # 2. Embedding (Tokens used)
            embeddings, embed_tokens = await self.embedder.generate_embeddings_batch(chunks)
            # tracker.record_usage(op_id, 0, 0, settings.EMBEDDING_MODEL, "embedding") # Cost calculated manually or via tracker if integrated
            # We record usage directly:
            tracker.record_usage(op_id, embed_tokens, 0, settings.EMBEDDING_MODEL, "embedding_api")

            # 3. Postgres Ingestion (Updated for new Schema)
            # Insert Document Parent
            doc_id = await insert_document(
                title=filename,
                source=filename,
                content=content,
                metadata={"source_type": "markdown", "filename": filename}
            )
            
            # Insert Chunks
            await insert_chunks(doc_id, chunks, embeddings)


            
            # 4. Graph Ingestion
            if not skip_graphiti:
                # Each chunk (or whole doc?) added to graph
                # Adding whole doc to graphiti provides better context
                await GraphClient.add_episode(content, filename)
            
            # Logging
            latency = time.time() - start_time
            metrics = tracker.end_operation(op_id)

            cost = metrics.cost_usd if metrics else 0.0
            
            ingestion_logger.log_row({
                "episodio_id": op_id,
                "timestamp": start_time,
                "source_type": "markdown",
                "nombre_archivo": filename,
                "longitud_palabras": len(content.split()),
                "chunks_creados": len(chunks),
                "embeddings_tokens": embed_tokens,
                "costo_total_usd": cost,
                "tiempo_seg": latency
            })
            
            logger.info(f"Ingested {filename}: Cost ${cost:.4f}, Time {latency:.2f}s")
            
        except Exception as e:
            logger.error(f"Failed to ingest {file_path}: {e}")
            tracker.end_operation(op_id)
            raise

async def ingest_directory(directory: str, skip_graphiti: bool = False):
    pipeline = DocumentIngestionPipeline()
    await DatabasePool.init_db()
    
    files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(".md")]
    
    # Concurrency limit (conservative for 1 vCPU / 2GB RAM target)
    sem = asyncio.Semaphore(5)
    
    async def bound_ingest(f: str):
        async with sem:
            await pipeline.ingest_file(f, skip_graphiti=skip_graphiti)
    
    msg = " (Postgres Only)" if skip_graphiti else " (Postgres + Graphiti)"
    logger.info(f"Ingesting {len(files)} files with concurrency=5{msg}...")
    
    await asyncio.gather(*(bound_ingest(f) for f in files))



if __name__ == "__main__":
    # Script entry point
    import argparse
    import json
    
    # Simple CLI
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=str, help="Directory to ingest")
    args = parser.parse_args()
    
    if args.dir:
        asyncio.run(ingest_directory(args.dir))
