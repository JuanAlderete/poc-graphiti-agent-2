import csv
import os
import logging
from datetime import datetime
from threading import Lock

logger = logging.getLogger(__name__)

class CsvLogger:
    def __init__(self, file_path: str, headers: list):
        self.file_path = file_path
        self.headers = headers
        self._lock = Lock()
        self._initialize_file()

    def _initialize_file(self):
        """Creates file with headers if it doesn't exist."""
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        
        if not os.path.exists(self.file_path):
            with open(self.file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(self.headers)

    def log_row(self, row_dict: dict):
        """Logs a single row to the CSV file safely."""
        with self._lock:
            try:
                with open(self.file_path, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=self.headers)
                    # Filter row_dict to match headers only (safe logging)
                    filtered_row = {k: row_dict.get(k, "") for k in self.headers}
                    writer.writerow(filtered_row)
            except Exception as e:
                logger.error(f"Failed to write to log {self.file_path}: {e}")

    def reset(self):
        """Clears the log file and re-writes headers."""
        with self._lock:
            try:
                if os.path.exists(self.file_path):
                    os.remove(self.file_path)
                self._initialize_file()
                logger.info(f"Log reset: {self.file_path}")
            except Exception as e:
                logger.error(f"Failed to reset log {self.file_path}: {e}")

def clear_all_logs():
    """Resets all CSV loggers."""
    ingestion_logger.reset()
    search_logger.reset()
    generation_logger.reset()


# Define Loggers

# 1. Ingestion Log
INGESTION_LOG_PATH = os.path.join("logs", "ingesta_log.csv")
INGESTION_HEADERS = [
    "episodio_id", "timestamp", "source_type", "nombre_archivo", "longitud_palabras",
    "orden_ingesta", "preproceso_tokens_in", "preproceso_tokens_out",
    "graphiti_tokens_in", "graphiti_tokens_out", "embeddings_tokens",
    "entidades_extraidas", "relaciones_creadas", "chunks_creados", "tiempo_seg",
    "costo_preproceso_usd", "costo_graphiti_usd", "costo_embeddings_usd", "costo_total_usd"
]
ingestion_logger = CsvLogger(INGESTION_LOG_PATH, INGESTION_HEADERS)

# 2. Search Log
SEARCH_LOG_PATH = os.path.join("logs", "busqueda_log.csv")
SEARCH_HEADERS = [
    "query_id", "timestamp", "query_texto", "longitud_query", 
    "tipo_busqueda", "tokens_embedding", "tokens_llm_in", "tokens_llm_out",
    "costo_embedding_usd", "costo_llm_usd", "costo_total_usd",
    "resultados_retornados", "latencia_ms"
]
search_logger = CsvLogger(SEARCH_LOG_PATH, SEARCH_HEADERS)

# 3. Generation Log
GENERATION_LOG_PATH = os.path.join("logs", "generacion_log.csv")
GENERATION_HEADERS = [
    "pieza_id", "timestamp", "formato", "tema_base", 
    "tokens_contexto_in", "tokens_prompt_in", "tokens_out", 
    "modelo", "provider", "costo_usd", "tiempo_seg", 
    "longitud_output_chars"
]
generation_logger = CsvLogger(GENERATION_LOG_PATH, GENERATION_HEADERS)

def setup_loggers():
    """Ensures all loggers are initialized."""
    # (Loggers initialize themselves on import/creation)
    pass
