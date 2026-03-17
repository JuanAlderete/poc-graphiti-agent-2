import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Optional

from poc.config import config
from agent.db_utils import (
    DatabasePool,
    document_exists_by_hash,
    insert_document,
    insert_chunks,
    mark_document_graph_ingested,
)
from agent.graph_utils import GraphClient
from ingestion.chunker import SemanticChunker
from ingestion.embedder import get_embedder
from ingestion.taxonomy import TaxonomyManager
from poc.logging_utils import ingestion_logger
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    filename:       str
    doc_id:         Optional[str]
    chunks_created: int
    embed_tokens:   int
    cost_usd:       float
    elapsed_sec:    float
    skipped:        bool = False
    error:          Optional[str] = None
    # NUEVO: métricas de entidades
    entities_extracted: int = 0
    entity_extraction_cost_usd: float = 0.0


class IngestionService:
    """
    Orquesta el pipeline completo de ingesta para un documento.

    PIPELINE v3.0:
        ① Deduplicación por hash
        ② Chunking
        ③ Token counts
        ④ Embeddings (batch)
        ⑤ Clasificación + extracción de entidades por chunk (TaxonomyManager v2.0)
        ⑥ Postgres: documento
        ⑦ Postgres: chunks con metadata enriquecida (entities, relationships, topics, etc.)
        ⑧ Graphiti/Neo4j (opcional)

    El paso ⑤ es el nuevo. Cada chunk pasa por:
        - Clasificación por keywords (siempre, gratis)
        - Extracción de entidades por LLM (si ENABLE_ENTITY_EXTRACTION=true y budget permite)
    """

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100):
        self.chunker = SemanticChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.embedder = get_embedder()
        self.taxonomy = TaxonomyManager()

    async def ingest_document(
        self,
        content: str,
        filename: str,
        skip_graphiti: bool = False,
        source_type: str = "markdown",
        extra: Optional[dict] = None,
    ) -> IngestionResult:
        """
        Ingesta un documento completo con enriquecimiento de entidades.

        Args:
            content:        Texto completo del documento
            filename:       Nombre del archivo (usado para clasificación)
            skip_graphiti:  True = solo Postgres, False = también Neo4j
            source_type:    Tipo de documento ("markdown", "transcript", etc.)
            extra:          Metadata extra conocida (edition, alumno_id, etc.)
        """
        start_time = time.time()
        op_id = f"ingest_{filename}_{int(start_time)}"
        tracker.start_operation(op_id, "ingestion")

        try:
            # ── ① Deduplicación ───────────────────────────────────────────
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            if await document_exists_by_hash(content_hash):
                logger.info("Skipping '%s' — already ingested (hash=%s)", filename, content_hash)
                tracker.end_operation(op_id)
                return IngestionResult(
                    filename=filename, doc_id=None, chunks_created=0,
                    embed_tokens=0, cost_usd=0.0,
                    elapsed_sec=time.time() - start_time, skipped=True
                )

            # ── ② Chunking ────────────────────────────────────────────────
            chunks = self.chunker.chunk(content)
            logger.info("'%s': %d chunks creados", filename, len(chunks))

            # ── ③ Token counts ────────────────────────────────────────────
            chunk_token_counts = [tracker.estimate_tokens(c) for c in chunks]

            # ── ④ Embeddings en batch ─────────────────────────────────────
            embeddings, embed_tokens = await self.embedder.generate_embeddings_batch(chunks)
            tracker.record_usage(op_id, embed_tokens, 0, config.EMBEDDING_MODEL, "embedding_api")

            # ── ⑤ Clasificación + extracción de entidades por chunk ───────
            # Este es el paso nuevo. classify_and_enrich() hace:
            #   - Keywords: source_type, domain, topics, emotion, content_level (siempre)
            #   - LLM: entities, relationships (solo si ENABLE_ENTITY_EXTRACTION=true)
            metadata_list = []
            total_entities = 0
            entity_cost = 0.0

            enable_entities = getattr(config, 'ENABLE_ENTITY_EXTRACTION', True)

            for i, chunk_text in enumerate(chunks):
                try:
                    if enable_entities:
                        chunk_meta = await self.taxonomy.classify_and_enrich(
                            content=chunk_text,
                            filename=filename,
                            extra=extra,
                        )
                    else:
                        chunk_meta = self.taxonomy.classify(
                            content=chunk_text,
                            filename=filename,
                            extra=extra,
                        )

                    meta_dict = chunk_meta.to_dict()
                    # Agregar content_hash del documento al chunk para trazabilidad
                    meta_dict["doc_content_hash"] = content_hash

                    metadata_list.append(meta_dict)
                    total_entities += len(chunk_meta.entities)

                except Exception as e:
                    logger.warning("Taxonomy/entity extraction failed for chunk %d: %s", i, e)
                    metadata_list.append({
                        "source_type": source_type,
                        "filename": filename,
                        "doc_content_hash": content_hash,
                        "entities": [],
                        "relationships": [],
                    })

            logger.info(
                "'%s': %d entidades extraídas en %d chunks",
                filename, total_entities, len(chunks)
            )

            # ── ⑥ Postgres — documento ────────────────────────────────────
            doc_id = await insert_document(
                title=filename,
                source=filename,
                content=content,
                metadata={
                    "source_type": source_type,
                    "filename": filename,
                    "content_hash": content_hash,
                    **(extra or {}),
                },
            )

            # ── ⑦ Postgres — chunks con metadata enriquecida ─────────────
            # Ahora cada chunk tiene su propia metadata con entities y relationships
            await insert_chunks(
                doc_id=doc_id,
                chunks=chunks,
                embeddings=embeddings,
                token_counts=chunk_token_counts,
                metadata_list=metadata_list,   # ← NUEVO: metadata por chunk
            )

            # ── ⑧ Graphiti / Neo4j (opcional) ────────────────────────────
            if not skip_graphiti and config.ENABLE_GRAPH:
                ep_uuid = await GraphClient.add_episode(content, filename)
                await mark_document_graph_ingested(doc_id, ep_uuid)

            elapsed = time.time() - start_time
            metrics = tracker.end_operation(op_id)
            cost = metrics.cost_usd if metrics else 0.0

            ingestion_logger.log_row({
                "episodio_id":     op_id,
                "timestamp":       start_time,
                "source_type":     source_type,
                "nombre_archivo":  filename,
                "longitud_palabras": len(content.split()),
                "chunks_creados":  len(chunks),
                "embeddings_tokens": embed_tokens,
                "entidades_extraidas": total_entities,
                "costo_total_usd": cost,
                "tiempo_seg":      elapsed,
            })

            logger.info(
                "Ingested '%s': chunks=%d entities=%d cost=$%.4f time=%.1fs",
                filename, len(chunks), total_entities, cost, elapsed
            )

            return IngestionResult(
                filename=filename,
                doc_id=doc_id,
                chunks_created=len(chunks),
                embed_tokens=embed_tokens,
                cost_usd=cost,
                elapsed_sec=elapsed,
                entities_extracted=total_entities,
                entity_extraction_cost_usd=entity_cost,
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