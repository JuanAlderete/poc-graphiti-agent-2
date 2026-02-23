"""
Servicio de ingesta desacoplado de la fuente de datos.
HOY: se le pasa el contenido directamente (desde archivos locales).
FUTURO: se le pasará desde Google Drive, webhooks n8n, etc.
No importar nada de Streamlit ni de argparse aquí.
"""
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Optional

from agent.config import settings
from agent.db_utils import DatabasePool, document_exists_by_hash, insert_document, insert_chunks
from agent.graph_utils import GraphClient
from ingestion.chunker import SemanticChunker
from ingestion.embedder import get_embedder
from poc.logging_utils import ingestion_logger
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    filename: str
    doc_id: Optional[str]
    chunks_created: int
    embed_tokens: int
    cost_usd: float
    elapsed_sec: float
    skipped: bool = False   # True si ya existía por hash
    error: Optional[str] = None


class IngestionService:
    """
    Orquesta el pipeline completo de ingesta para un documento.

    Uso actual (POC):
        service = IngestionService()
        result = await service.ingest_document(content, filename, skip_graphiti=True)

    Uso futuro (FastAPI):
        # Mismo código, solo cambia quién llama al método
        @app.post("/ingest")
        async def ingest_endpoint(req: IngestRequest):
            result = await service.ingest_document(req.content, req.filename)
            return result
    """

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100):
        self.chunker = SemanticChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.embedder = get_embedder()

    async def ingest_document(
        self,
        content: str,
        filename: str,
        skip_graphiti: bool = False,
        source_type: str = "markdown",
    ) -> IngestionResult:
        """
        Ingesta un documento completo.

        Args:
            content: Texto completo del documento.
            filename: Nombre de archivo (ej: 'alex.md'). Usado como source reference.
            skip_graphiti: Si True, solo ingesta en Postgres (sin Neo4j).
            source_type: Tipo de fuente ('markdown', 'transcript', 'pdf', etc.)

        Returns:
            IngestionResult con métricas detalladas.
        """
        start_time = time.time()
        op_id = f"ingest_{filename}_{int(start_time)}"
        tracker.start_operation(op_id, "ingestion")

        try:
            # 1. Deduplicación por hash
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            if await document_exists_by_hash(content_hash):
                logger.info("Skipping '%s' — already ingested (hash=%s)", filename, content_hash)
                tracker.end_operation(op_id)
                return IngestionResult(
                    filename=filename, doc_id=None, chunks_created=0,
                    embed_tokens=0, cost_usd=0.0,
                    elapsed_sec=time.time() - start_time, skipped=True
                )

            # 2. Chunking
            chunks = self.chunker.chunk(content)

            # 3. Embeddings batch
            embeddings, embed_tokens = await self.embedder.generate_embeddings_batch(chunks)
            tracker.record_usage(op_id, embed_tokens, 0, settings.EMBEDDING_MODEL, "embedding_api")

            # 4. Postgres — documento
            doc_id = await insert_document(
                title=filename,
                source=filename,
                content=content,
                metadata={
                    "source_type": source_type,
                    "filename": filename,
                    "content_hash": content_hash,
                },
            )

            # 5. Postgres — chunks
            await insert_chunks(doc_id, chunks, embeddings)

            # 6. Graphiti / Neo4j (opcional)
            if not skip_graphiti:
                await GraphClient.add_episode(content, filename)
                # Marcar como hidratado en metadata
                from agent.db_utils import mark_document_graph_ingested
                await mark_document_graph_ingested(doc_id)

            elapsed = time.time() - start_time
            metrics = tracker.end_operation(op_id)
            cost = metrics.cost_usd if metrics else 0.0

            ingestion_logger.log_row({
                "episodio_id": op_id,
                "timestamp": start_time,
                "source_type": source_type,
                "nombre_archivo": filename,
                "longitud_palabras": len(content.split()),
                "chunks_creados": len(chunks),
                "embeddings_tokens": embed_tokens,
                "costo_total_usd": cost,
                "tiempo_seg": elapsed,
            })

            logger.info("Ingested '%s': chunks=%d cost=$%.4f time=%.1fs", filename, len(chunks), cost, elapsed)
            return IngestionResult(
                filename=filename, doc_id=doc_id, chunks_created=len(chunks),
                embed_tokens=embed_tokens, cost_usd=cost, elapsed_sec=elapsed
            )

        except Exception as exc:
            logger.exception("Failed to ingest '%s'", filename)
            tracker.end_operation(op_id)
            return IngestionResult(
                filename=filename, doc_id=None, chunks_created=0,
                embed_tokens=0, cost_usd=0.0,
                elapsed_sec=time.time() - start_time,
                error=str(exc)
            )
