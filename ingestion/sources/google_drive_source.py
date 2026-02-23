"""
STUB para fuente Google Drive.
NO IMPLEMENTADO — estructura lista para Fase 1.

Para implementar en Fase 1:
1. pip install google-api-python-client google-auth
2. Crear OAuth2 credentials en Google Cloud Console
3. Implementar los métodos con la Google Drive API v3
4. El resto del pipeline de ingesta NO cambia.

Alternativa Fase 1 (más simple con n8n):
    n8n detecta archivo en Drive → llama POST /ingest con {content, filename}
    En ese caso, NO hace falta esta clase. El endpoint FastAPI crea un DocumentPayload
    directamente desde el body del request y llama a IngestionService.ingest_document().
"""
import logging
from typing import Optional

from ingestion.sources.base import DocumentSource, DocumentPayload

logger = logging.getLogger(__name__)


class GoogleDriveSource(DocumentSource):
    """
    Fuente de documentos desde Google Drive.

    FASE 1 — PENDIENTE DE IMPLEMENTAR.

    Args:
        folder_id: ID de la carpeta en Google Drive a monitorear.
        credentials_path: Path al archivo JSON de credenciales OAuth2.
        file_extensions: Extensiones a procesar (default: .md, .txt, .docx).
    """

    def __init__(
        self,
        folder_id: str,
        credentials_path: str = "credentials.json",
        file_extensions: Optional[list] = None,
    ):
        self.folder_id = folder_id
        self.credentials_path = credentials_path
        self.file_extensions = file_extensions or [".md", ".txt", ".docx"]
        logger.warning(
            "GoogleDriveSource is NOT YET IMPLEMENTED. "
            "Use LocalFileSource for now or implement Google Drive API v3 calls."
        )

    async def list_documents(self) -> list[DocumentPayload]:
        """
        TODO Fase 1: Implementar con google-api-python-client.

        Pasos:
            1. Autenticar con OAuth2 usando credentials_path
            2. Listar archivos en folder_id con mimeType filter
            3. Descargar contenido de cada archivo
            4. Convertir a DocumentPayload
            5. Filtrar por archivos modificados desde última ejecución (usar Drive webhook o polling)
        """
        raise NotImplementedError(
            "GoogleDriveSource.list_documents() not implemented. "
            "Implement in Fase 1 using Google Drive API v3."
        )

    def source_name(self) -> str:
        return f"google_drive:{self.folder_id}"
