import asyncio
import hashlib
import logging
import os
import time
from typing import List

from agent.config import settings
from agent.db_utils import (
    DatabasePool,
    document_exists_by_hash,
    insert_chunks,
    insert_document,
    mark_document_graph_ingested,
)
from agent.graph_utils import GraphClient
from ingestion.chunker import SemanticChunker
from ingestion.embedder import EmbeddingGenerator
from poc.logging_utils import ingestion_logger
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)


class DocumentIngestionPipeline:
    def __init__(self):
        self.chunker = SemanticChunker(chunk_size=800, chunk_overlap=100)
        self.embedder = EmbeddingGenerator()

    async def ingest_file(
        self, file_path: str, skip_graphiti: bool = False
    ) -> float:
        """
        Ingesta un archivo en Postgres y opcionalmente Graphiti.
        Retorna el costo estimado en USD.

        Flujo completo de metadata:
          ① document_exists_by_hash()   → deduplicación por contenido
          ② insert_document()           → title, source, content,
                                          metadata{source_type, filename, content_hash}
          ③ insert_chunks()             → token_count por chunk
          ④ mark_document_graph_ingested(ep_uuid)
                                        → metadata.graph_ingested=true + graphiti_episode_id
        """
        start_time = time.time()
        filename = os.path.basename(file_path)
        op_id = f"ingest_{filename}_{int(start_time)}"
        tracker.start_operation(op_id, "ingestion")

        cost = 0.0

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 0. Deduplicación por hash
            # FIX: antes no existía esta verificación en DocumentIngestionPipeline.
            #      Al re-ejecutar ingest_directory se duplicaban los documentos en Postgres.
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            if await document_exists_by_hash(content_hash):
                logger.info("Skipping '%s' — already ingested (hash=%s)", filename, content_hash)
                tracker.end_operation(op_id)
                return 0.0

            # 1. Chunking
            chunks = self.chunker.chunk(content)

            # 2. Token counts por chunk
            chunk_token_counts = [tracker.estimate_tokens(c) for c in chunks]

            # 3. Embeddings en batch (una sola llamada a la API)
            embeddings, embed_tokens = await self.embedder.generate_embeddings_batch(chunks)
            tracker.record_usage(op_id, embed_tokens, 0, settings.EMBEDDING_MODEL, "embedding_api")

            # 4. Postgres — documento
            # FIX: antes metadata no incluía content_hash → el índice idx_documents_content_hash
            #      nunca se populaba y la deduplicación en IngestionService no encontraba
            #      documentos ingresados por DocumentIngestionPipeline.
            doc_id = await insert_document(
                title=filename,
                source=filename,
                content=content,
                metadata={
                    "source_type": "markdown",
                    "filename": filename,
                    "content_hash": content_hash,
                },
            )

            # 5. Postgres — chunks con token counts
            await insert_chunks(doc_id, chunks, embeddings, token_counts=chunk_token_counts)

            # 6. Graphiti (si está activo)
            if not skip_graphiti:
                ep_uuid = await GraphClient.add_episode(content, filename)
                await mark_document_graph_ingested(doc_id, ep_uuid)

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
                "tiempo_seg": latency,
            })

            logger.info("Ingested %s: chunks=%d cost=$%.4f time=%.1fs", filename, len(chunks), cost, latency)

        except Exception:
            logger.exception("Failed to ingest %s — skipping.", file_path)
            tracker.end_operation(op_id)
            cost = 0.0

        return cost


async def ingest_directory(directory: str, skip_graphiti: bool = False, max_files: int = 0) -> None:
    await DatabasePool.init_db()

    if not skip_graphiti:
        await GraphClient.ensure_schema()

    files = sorted([
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.endswith(".md")
    ])

    if max_files > 0:
        files = files[:max_files]
        logger.info("Limiting ingestion to %d file(s).", max_files)

    if not files:
        logger.warning("No .md files found in '%s'.", directory)
        return

    concurrency = 1 if not skip_graphiti else 8
    sem = asyncio.Semaphore(concurrency)
    pipeline = DocumentIngestionPipeline()
    t0 = time.time()

    async def _bound(f: str) -> float:
        async with sem:
            return await pipeline.ingest_file(f, skip_graphiti=skip_graphiti)

    mode = "Postgres Only" if skip_graphiti else "Postgres + Graphiti (secuencial)"
    logger.info("Ingesting %d files [%s, concurrencia=%d]...", len(files), mode, concurrency)

    results = await asyncio.gather(*(_bound(f) for f in files), return_exceptions=True)

    successes = sum(1 for r in results if isinstance(r, float))
    errors = sum(1 for r in results if isinstance(r, Exception))
    total_cost = sum(r for r in results if isinstance(r, float))
    elapsed = time.time() - t0

    logger.info(
        "Ingestion done: %d/%d archivos en %.1fs — total $%.4f — errores: %d",
        successes, len(files), elapsed, total_cost, errors,
    )


async def ingest_files(file_paths: List[str], skip_graphiti: bool = False) -> None:
    """
    Ingesta una lista explícita de rutas de archivo.
    Usada por el file uploader del dashboard.
    """
    await DatabasePool.init_db()

    if not skip_graphiti:
        await GraphClient.ensure_schema()

    if not file_paths:
        logger.warning("ingest_files: lista vacía, nada que ingestar.")
        return

    concurrency = 1 if not skip_graphiti else 8
    sem = asyncio.Semaphore(concurrency)
    pipeline = DocumentIngestionPipeline()
    t0 = time.time()

    async def _bound(f: str) -> float:
        async with sem:
            return await pipeline.ingest_file(f, skip_graphiti=skip_graphiti)

    mode = "Postgres Only" if skip_graphiti else "Postgres + Graphiti"
    logger.info("Ingesting %d specific files [%s]...", len(file_paths), mode)

    results = await asyncio.gather(*(_bound(f) for f in file_paths), return_exceptions=True)

    successes = sum(1 for r in results if isinstance(r, float))
    errors = sum(1 for r in results if isinstance(r, Exception))
    total_cost = sum(r for r in results if isinstance(r, float))
    elapsed = time.time() - t0

    logger.info(
        "ingest_files done: %d/%d archivos en %.1fs — total $%.4f — errores: %d",
        successes, len(file_paths), elapsed, total_cost, errors,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--skip-graphiti", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(ingest_directory(args.dir, skip_graphiti=args.skip_graphiti))


async def ingest_from_source(
    source,
    skip_graphiti: bool = False,
    concurrency: int = 1,
) -> dict:
    """
    Ingesta documentos desde cualquier implementación de DocumentSource.
    """
    from services.ingestion_service import IngestionService

    await DatabasePool.init_db()
    if not skip_graphiti:
        await GraphClient.ensure_schema()

    logger.info("Listing documents from source: %s", source.source_name())
    docs = await source.list_documents()

    if not docs:
        logger.warning("No documents found in source: %s", source.source_name())
        return {"successes": 0, "errors": 0, "total_cost_usd": 0.0, "elapsed_sec": 0.0}

    t0 = time.time()
    service = IngestionService()
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _ingest_one(doc):
        async with sem:
            return await service.ingest_document(
                content=doc.content,
                filename=doc.filename,
                skip_graphiti=skip_graphiti,
                source_type=doc.source_type,
            )

    results = await asyncio.gather(*(_ingest_one(doc) for doc in docs), return_exceptions=True)

    successes = sum(1 for r in results if hasattr(r, "chunks_created") and not r.error and not r.skipped)
    errors = sum(1 for r in results if isinstance(r, Exception) or (hasattr(r, "error") and r.error))
    total_cost = sum(r.cost_usd for r in results if hasattr(r, "cost_usd") and r.cost_usd)
    elapsed = time.time() - t0

    logger.info(
        "ingest_from_source done: %d/%d ok — errors: %d — cost: $%.4f — time: %.1fs",
        successes, len(docs), errors, total_cost, elapsed
    )
    return {
        "successes": successes,
        "errors": errors,
        "total_cost_usd": round(total_cost, 6),
        "elapsed_sec": round(elapsed, 2),
    }