"""
api/routes/ingest.py
--------------------
POST /ingest — Ingesta un documento en Postgres (y opcionalmente Neo4j).

Llamado por n8n cuando detecta un archivo nuevo en Google Drive.
También puede llamarse directamente desde scripts o tests.

Flujo:
    1. Recibe filename + content + metadata
    2. Llama a IngestionService.ingest_document()
       ├── Deduplicación por hash
       ├── Chunking
       ├── Embeddings batch
       ├── TaxonomyManager.classify_and_enrich() por chunk
       └── insert_document() + insert_chunks() en Postgres
    3. Retorna doc_id, chunks_count, entities_extracted, cost_usd
"""
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks

from api.models.ingest import IngestRequest, IngestResponse
from services.ingestion_service import IngestionService
from agent.db_utils import DatabasePool

logger = logging.getLogger(__name__)
router = APIRouter()

# Singleton del servicio (se crea una vez, se reutiliza)
_ingestion_service: IngestionService | None = None


def get_ingestion_service() -> IngestionService:
    global _ingestion_service
    if _ingestion_service is None:
        _ingestion_service = IngestionService()
    return _ingestion_service


@router.post("/ingest", response_model=IngestResponse, tags=["Ingesta"])
async def ingest_document(request: IngestRequest) -> IngestResponse:
    """
    Ingesta un documento en Postgres.

    - Deduplicación automática por hash de contenido
    - Chunking recursivo (800 chars, 100 overlap)
    - Embeddings en batch (una sola llamada a la API)
    - Clasificación por keywords + extracción de entidades LLM (si ENABLE_ENTITY_EXTRACTION=true)
    - Guarda en Postgres con metadata enriquecida por chunk

    Si el documento ya fue ingestado (mismo hash), retorna `skipped: true` sin gastar.
    """
    logger.info(
        "POST /ingest: filename='%s' source_type='%s' org='%s'",
        request.filename, request.source_type, request.organization_id
    )

    if not request.content or not request.content.strip():
        raise HTTPException(status_code=400, detail="El campo 'content' no puede estar vacío")

    if len(request.content) < 50:
        raise HTTPException(
            status_code=400,
            detail=f"Contenido demasiado corto ({len(request.content)} chars). Mínimo 50 caracteres."
        )

    try:
        # Asegurar que la DB está inicializada
        await DatabasePool.init_db()

        service = get_ingestion_service()
        result = await service.ingest_document(
            content=request.content,
            filename=request.filename,
            skip_graphiti=request.skip_graphiti,
            source_type=request.source_type,
            extra={
                **request.extra,
                "organization_id": request.organization_id,
            },
        )

        if result.error:
            logger.error("Ingesta de '%s' falló: %s", request.filename, result.error)
            raise HTTPException(status_code=500, detail=result.error)

        logger.info(
            "Ingesta completada: '%s' → %d chunks, %d entidades, $%.4f",
            request.filename,
            result.chunks_created,
            result.entities_extracted,
            result.cost_usd,
        )

        return IngestResponse(
            doc_id=result.doc_id,
            chunks_count=result.chunks_created,
            entities_extracted=result.entities_extracted,
            cost_usd=round(result.cost_usd, 6),
            skipped=result.skipped,
            organization_id=request.organization_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error inesperado en POST /ingest para '%s'", request.filename)
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")