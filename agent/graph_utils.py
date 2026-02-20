import logging
import re
import time
import uuid
from datetime import datetime
from typing import List, Optional

from graphiti_core import Graphiti

from agent.config import settings
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)

# Truncado de contenido antes de Graphiti.
# Graphiti hace ~30 llamadas LLM internas, cada una con el texto completo.
# 6000 chars ≈ 1500 tokens. Las entidades clave siempre están al inicio.
_MAX_EPISODE_CHARS = 6_000

# Resultados de búsqueda en grafo: cada resultado va al prompt de generación.
# 3 resultados es suficiente y reduce tokens de entrada en generación.
_GRAPH_SEARCH_LIMIT = 3

_MD_STRIP = [
    (re.compile(r"\[([^\]]*)\]\([^\)]*\)"), r"\1"),
    (re.compile(r"#{1,6}\s+", re.MULTILINE), ""),
    (re.compile(r"[*_`]{1,3}"), ""),
    (re.compile(r"^\s*[-*+]\s+", re.MULTILINE), ""),
    (re.compile(r"^\s*\d+\.\s+", re.MULTILINE), ""),
    (re.compile(r"^>\s*", re.MULTILINE), ""),
    (re.compile(r"\n{3,}"), "\n\n"),
]


def _strip_markdown(text: str) -> str:
    for pattern, repl in _MD_STRIP:
        text = pattern.sub(repl, text)
    return text.strip()


class GraphClient:
    _client: Optional[Graphiti] = None
    _initialized: bool = False

    @classmethod
    def _build_client(cls) -> Graphiti:
        provider = settings.LLM_PROVIDER.lower()

        if provider == "gemini":
            from agent.gemini_client import GeminiClient
            from graphiti_core.embedder.gemini import GeminiEmbedder
            logger.info("Inicializando Graphiti con Gemini...")
            return Graphiti(
                uri=settings.NEO4J_URI,
                user=settings.NEO4J_USER,
                password=settings.NEO4J_PASSWORD,
                llm_client=GeminiClient(model_name=settings.DEFAULT_MODEL),
                embedder=GeminiEmbedder(),
            )

        # OpenAI — usa CustomOpenAIClient para fix de reasoning model + retry
        from agent.custom_openai_client import CustomOpenAIClient
        from graphiti_core.llm_client.config import LLMConfig
        logger.info("Inicializando Graphiti con CustomOpenAI (%s)...", settings.DEFAULT_MODEL)
        return Graphiti(
            uri=settings.NEO4J_URI,
            user=settings.NEO4J_USER,
            password=settings.NEO4J_PASSWORD,
            llm_client=CustomOpenAIClient(
                config=LLMConfig(
                    api_key=settings.OPENAI_API_KEY,
                    model=settings.DEFAULT_MODEL,
                )
            ),
        )

    @classmethod
    def get_client(cls) -> Graphiti:
        """Retorna el cliente Graphiti (solo construcción, sin índices)."""
        if cls._client is None:
            try:
                cls._client = cls._build_client()
                logger.info("Graphiti client creado (provider=%s).", settings.LLM_PROVIDER)
            except Exception:
                logger.exception("Error al construir Graphiti client")
                raise
        return cls._client

    @classmethod
    async def ensure_schema(cls) -> None:
        """
        Inicializa el cliente Y crea todos los índices/constraints de Neo4j.
        Reemplaza la versión original que creaba índices manualmente (incompletos).
        Llama a build_indices_and_constraints() de graphiti-core, que es la
        forma oficial y garantiza compatibilidad con la versión instalada.
        """
        client = cls.get_client()
        if not cls._initialized:
            try:
                logger.info("Creando índices Neo4j via build_indices_and_constraints()...")
                await client.build_indices_and_constraints()
                cls._initialized = True
                logger.info("Índices Neo4j listos.")
            except Exception:
                logger.exception("Error al crear índices Neo4j")
                raise

    @classmethod
    async def add_episode(
        cls,
        content: str,
        source_reference: str,
        source_description: Optional[str] = None,
    ) -> None:
        """
        Agrega un episodio al knowledge graph.

        Optimizaciones aplicadas antes de llamar a Graphiti:
          1. Strip de Markdown (elimina tokens de sintaxis inútiles)
          2. Truncado a _MAX_EPISODE_CHARS (reduce ~60% del costo interno de Graphiti)
        """
        client = cls.get_client()

        # Strip MD y truncar
        content_clean = _strip_markdown(content)
        original_len = len(content_clean)
        if original_len > _MAX_EPISODE_CHARS:
            content_clean = content_clean[:_MAX_EPISODE_CHARS]

        op_id = f"graph_ingest_{uuid.uuid4().hex[:8]}"
        estimated_in = tracker.estimate_tokens(content_clean)
        tracker.start_operation(op_id, "graph_ingestion")

        description = source_description or f"Ingestion from {source_reference}"

        try:
            from graphiti_core.nodes import EpisodeType
            await client.add_episode(
                name=source_reference,
                episode_body=content_clean,
                source_description=description,
                reference_time=datetime.now(),
                source=EpisodeType.text,
            )

            tracker.record_usage(
                op_id,
                estimated_in,
                int(estimated_in * 0.30),
                settings.DEFAULT_MODEL,
                "graphiti_add_episode",
            )

        except Exception:
            logger.exception("Error en add_episode (%s)", source_reference)
            raise
        finally:
            metrics = tracker.end_operation(op_id)
            if metrics:
                logger.info(
                    "Graph episode '%s': $%.4f (in=%d tokens) [%d/%d chars]",
                    source_reference,
                    metrics.cost_usd,
                    metrics.tokens_in,
                    len(content_clean),
                    original_len,
                )

    @classmethod
    async def search(cls, query: str, num_results: int = _GRAPH_SEARCH_LIMIT) -> List[str]:
        """Busca en el knowledge graph. Retorna lista de strings."""
        client = cls.get_client()
        try:
            results = await client.search(query, num_results=num_results)
            if not results:
                return []
            output = []
            for r in results:
                if hasattr(r, "fact"):
                    output.append(str(r.fact))
                elif hasattr(r, "content"):
                    output.append(str(r.content))
                else:
                    output.append(str(r))
            return output
        except Exception:
            logger.exception("Error en graph search: %s", query)
            return []

    @classmethod
    def reset(cls) -> None:
        """Resetea el singleton. Útil en tests."""
        cls._client = None
        cls._initialized = False