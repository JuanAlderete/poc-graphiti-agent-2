"""
Fuente de documentos desde archivos locales.
Reemplaza la lógica de os.listdir() dispersa en ingest.py y run_poc.py.
"""
import logging
from pathlib import Path
from typing import Optional

from ingestion.sources.base import DocumentSource, DocumentPayload

logger = logging.getLogger(__name__)

# Extensiones soportadas por defecto
_DEFAULT_EXTENSIONS = {".md", ".txt"}


class LocalFileSource(DocumentSource):
    """
    Lee documentos desde un directorio local.

    Uso:
        source = LocalFileSource("documents_to_index")
        docs = await source.list_documents()

    Para migrar a Google Drive en Fase 1:
        source = GoogleDriveSource(folder_id="...", credentials=creds)
        # El resto del pipeline NO cambia.
    """

    def __init__(
        self,
        directory: str,
        extensions: Optional[set] = None,
        recursive: bool = False,
    ):
        self.directory = Path(directory)
        self.extensions = extensions or _DEFAULT_EXTENSIONS
        self.recursive = recursive

    async def list_documents(self) -> list[DocumentPayload]:
        if not self.directory.exists():
            logger.error("Directory not found: %s", self.directory)
            return []

        pattern = "**/*" if self.recursive else "*"
        files = sorted(
            f for f in self.directory.glob(pattern)
            if f.is_file() and f.suffix.lower() in self.extensions
        )

        if not files:
            logger.warning("No files found in '%s' with extensions %s", self.directory, self.extensions)
            return []

        docs = []
        for f in files:
            try:
                content = f.read_text(encoding="utf-8")
                docs.append(DocumentPayload(
                    filename=f.name,
                    content=content,
                    source_type="markdown" if f.suffix == ".md" else "text",
                    source_id=str(f.resolve()),
                    source_url=None,
                    metadata={"local_path": str(f)},
                ))
            except Exception:
                logger.exception("Error reading file: %s", f)

        logger.info("LocalFileSource: found %d documents in '%s'", len(docs), self.directory)
        return docs

    def source_name(self) -> str:
        return f"local:{self.directory}"
