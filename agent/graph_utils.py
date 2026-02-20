import logging
import uuid
from datetime import datetime
from typing import List, Optional

from graphiti_core import Graphiti

from agent.config import settings
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)

_GRAPHITI_OUTPUT_RATIO = 0.30  # estimación conservadora de tokens out/in


class GraphClient:
    _client: Optional[Graphiti] = None

    @classmethod
    def get_client(cls) -> Graphiti:
        if cls._client is not None:
            return cls._client

        provider = settings.LLM_PROVIDER.lower()
        try:
            if provider == "gemini":
                from agent.gemini_client import GeminiClient
                from graphiti_core.embedder.gemini import GeminiEmbedder
                logger.info("Initializing Graphiti with Gemini (%s)…", settings.DEFAULT_MODEL)
                cls._client = Graphiti(
                    uri=settings.NEO4J_URI,
                    user=settings.NEO4J_USER,
                    password=settings.NEO4J_PASSWORD,
                    llm_client=GeminiClient(model_name=settings.DEFAULT_MODEL),
                    embedder=GeminiEmbedder(),
                )
            else:
                from graphiti_core.llm_client.config import LLMConfig
                from graphiti_core.llm_client.openai_client import OpenAIClient
                logger.info("Initializing Graphiti with OpenAI (%s)…", settings.DEFAULT_MODEL)
                cls._client = Graphiti(
                    uri=settings.NEO4J_URI,
                    user=settings.NEO4J_USER,
                    password=settings.NEO4J_PASSWORD,
                    llm_client=OpenAIClient(
                        config=LLMConfig(api_key=settings.OPENAI_API_KEY, model=settings.DEFAULT_MODEL)
                    ),
                )
            logger.info("Graphiti client ready (provider=%s).", provider)
        except Exception:
            logger.exception("Failed to initialize Graphiti client")
            raise

        return cls._client

    @classmethod
    async def ensure_schema(cls) -> None:
        client = cls.get_client()
        try:
            await client.driver.execute_query(
                "CREATE FULLTEXT INDEX node_name_and_summary IF NOT EXISTS "
                "FOR (n:Entity) ON EACH [n.name, n.summary]"
            )
            await client.driver.execute_query(
                "CREATE CONSTRAINT entity_uuid IF NOT EXISTS "
                "FOR (n:Entity) REQUIRE n.uuid IS UNIQUE"
            )
            logger.info("Graphiti schema ensured.")
        except Exception:
            logger.exception("Schema setup failed — continuing anyway")

    @classmethod
    async def add_episode(
        cls,
        content: str,
        source_reference: str,
        source_description: Optional[str] = None,
    ) -> None:
        """
        Añade un episodio al knowledge graph.

        `source_description` es el parámetro clave para la migración eficiente.
        Cuando hydrate_graph.py lo rellena con el `graphiti_ready_context`
        pre-calculado en Fase 1, Graphiti puede:
          1. Saltar el prompt de "¿qué tipo de documento es esto?"
          2. Enfocar la extracción en las personas/empresas ya identificadas
          3. Reducir el total de tokens en ~20-30% por episodio
        """
        client = cls.get_client()
        estimated_input = tracker.estimate_tokens(content)
        op_id = f"graph_ingest_{uuid.uuid4().hex}"
        tracker.start_operation(op_id, "graph_ingestion")

        # Si no se provee descripción, generamos una básica
        effective_description = source_description or f"Ingestion from {source_reference}"

        try:
            from graphiti_core.nodes import EpisodeType
            await client.add_episode(
                name=source_reference,
                episode_body=content,
                source_description=effective_description,
                reference_time=datetime.now(),
                source=EpisodeType.text,
            )
            estimated_output = int(estimated_input * _GRAPHITI_OUTPUT_RATIO)
            tracker.record_usage(
                op_id, estimated_input, estimated_output,
                settings.DEFAULT_MODEL, "graphiti_add_episode",
            )
        except Exception:
            logger.exception("Error adding episode (%s)", source_reference)
            raise
        finally:
            metrics = tracker.end_operation(op_id)
            if metrics:
                logger.info("Graph episode %s: est. cost $%.4f", source_reference, metrics.cost_usd)

    @classmethod
    async def search(cls, query: str) -> List[str]:
        client = cls.get_client()
        results = await client.search(query)
        return [str(r) for r in results] if results else []