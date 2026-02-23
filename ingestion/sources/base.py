"""
Abstracción de fuente de documentos.
El pipeline de ingesta no sabe de dónde vienen los archivos.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional


@dataclass
class DocumentPayload:
    """
    Representa un documento listo para ingestar.

    Campos comunes para todas las fuentes (local, Google Drive, webhook n8n).
    """
    filename: str           # Nombre del archivo (ej: 'llamada_juan_2025-01-15.md')
    content: str            # Texto completo del documento
    source_type: str        # 'markdown' | 'transcript' | 'pdf_text' | 'notion_page'
    source_id: Optional[str] = None    # ID en la fuente original (ej: Google Drive file_id)
    source_url: Optional[str] = None   # URL original si aplica
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class DocumentSource(ABC):
    """
    Interface para fuentes de documentos.

    Implementaciones:
    - LocalFileSource (HOY): lee archivos .md de un directorio local
    - GoogleDriveSource (FUTURO Fase 1): lee desde Google Drive API
    - N8nWebhookSource (FUTURO Fase 1): recibe payload de n8n via HTTP
    - NotionSource (FUTURO Fase 2): lee páginas de Notion
    """

    @abstractmethod
    async def list_documents(self) -> list[DocumentPayload]:
        """
        Retorna todos los documentos disponibles en la fuente.
        Para fuentes grandes, preferir iter_documents().
        """
        ...

    async def iter_documents(self) -> AsyncIterator[DocumentPayload]:
        """
        Itera documentos uno a uno. Por defecto llama a list_documents().
        Sobreescribir para fuentes grandes o streaming.
        """
        for doc in await self.list_documents():
            yield doc

    @abstractmethod
    def source_name(self) -> str:
        """Nombre descriptivo de la fuente para logs."""
        ...
