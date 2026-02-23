import asyncio
import logging
import os
import time
from typing import List, Optional

from agent.config import settings
from agent.db_utils import DatabasePool, insert_chunks, insert_document
from agent.graph_utils import GraphClient
from ingestion.chunker import SemanticChunker
from ingestion.embedder import EmbeddingGenerator
from poc.logging_utils import ingestion_logger
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)


class DocumentIngestionPipeline:
    def __init__(self):
        # chunk_size 800 (vs 1000 original): chunks más precisos, menos tokens en generación
        # overlap 100 (vs 200 original): 50% menos tokens duplicados en embeddings
        self.chunker = SemanticChunker(chunk_size=800, chunk_overlap=100)
        self.embedder = EmbeddingGenerator()

    async def ingest_file(
        self, file_path: str, skip_graphiti: bool = False
    ) -> float:
        """
        Ingesta un archivo en Postgres y opcionalmente Graphiti.
        Retorna el costo estimado en USD. Nunca lanza excepciones hacia afuera
        (no re-raise), para que asyncio.gather() continue con los demas archivos.
        """
        start_time = time.time()
        filename = os.path.basename(file_path)
        op_id = f"ingest_{filename}_{int(start_time)}"
        tracker.start_operation(op_id, "ingestion")

        chunks: List[str] = []
        embed_tokens = 0
        cost = 0.0

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 1. Chunking
            chunks = self.chunker.chunk(content)

            # 2. Embeddings en batch (una sola llamada a la API)
            embeddings, embed_tokens = await self.embedder.generate_embeddings_batch(chunks)
            tracker.record_usage(op_id, embed_tokens, 0, settings.EMBEDDING_MODEL, "embedding_api")

            # 3. Postgres — documento
            doc_id = await insert_document(
                title=filename,
                source=filename,
                content=content,
                metadata={"source_type": "markdown", "filename": filename},
            )

            # 4. Postgres — chunks con embeddings
            await insert_chunks(doc_id, chunks, embeddings)

            # 5. Graphiti (si está activo)
            # El contenido se limpia y trunca dentro de GraphClient.add_episode()
            if not skip_graphiti:
                await GraphClient.add_episode(content, filename)

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

            logger.info(
                "Ingested %s: chunks=%d cost=$%.4f time=%.1fs",
                filename, len(chunks), cost, latency,
            )

        except Exception:
            # No re-raise: gather() continuará con los archivos restantes.
            # La versión original hacía `raise` aquí y eso causaba que
            # los archivos pendientes en el semáforo recibieran CancelledError.
            logger.exception(
                "Failed to ingest %s — skipping, continúa con el resto.", file_path
            )
            metrics = tracker.end_operation(op_id)
            cost = 0.0

        return cost


async def ingest_directory(directory: str, skip_graphiti: bool = False, max_files: int = 0) -> None:
    pipeline = DocumentIngestionPipeline()
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

    # CONCURRENCIA:
    # Con Graphiti activo: 1 (un episodio a la vez)
    #   Cada episodio dispara ~30 llamadas LLM internas en Graphiti.
    #   Con concurrencia > 1 se multiplican esas llamadas y causan 429.
    # Sin Graphiti: 8 (solo embeddings, baratos y sin LLM)
    concurrency = 1 if not skip_graphiti else 8
    sem = asyncio.Semaphore(concurrency)
    t0 = time.time()

    async def _bound(f: str) -> float:
        async with sem:
            return await pipeline.ingest_file(f, skip_graphiti=skip_graphiti)

    mode = "Postgres Only" if skip_graphiti else "Postgres + Graphiti (secuencial)"
    logger.info(
        "Ingesting %d files [%s, concurrencia=%d]...",
        len(files), mode, concurrency,
    )

    results = await asyncio.gather(*(_bound(f) for f in files), return_exceptions=True)

    successes = sum(1 for r in results if isinstance(r, float))
    errors = sum(1 for r in results if isinstance(r, Exception))
    total_cost = sum(r for r in results if isinstance(r, float))
    elapsed = time.time() - t0

    logger.info(
        "Ingestion done: %d/%d archivos en %.1fs — total $%.4f — errores: %d",
        successes, len(files), elapsed, total_cost, errors,
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

    Args:
        source: Cualquier instancia que implemente DocumentSource
                (LocalFileSource, GoogleDriveSource, etc.)
        skip_graphiti: Si True, solo ingesta en Postgres.
        concurrency: Cuántos documentos procesar en paralelo.
                     Mantener en 1 cuando Graphiti está activo.

    Returns:
        dict con {successes, errors, total_cost_usd, elapsed_sec}

    Ejemplo de uso con LocalFileSource:
        from ingestion.sources.local_file_source import LocalFileSource
        source = LocalFileSource("documents_to_index")
        result = await ingest_from_source(source)

    Ejemplo futuro con GoogleDriveSource:
        source = GoogleDriveSource(folder_id="1abc...")
        result = await ingest_from_source(source)
    """
    from services.ingestion_service import IngestionService

    pipeline = DocumentIngestionPipeline()
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