import logging
import uuid
from datetime import datetime
from typing import List

from graphiti_core import Graphiti

from agent.config import settings
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)

# Fraction of input tokens used as output estimate for Graphiti extraction.
# Graphiti runs entity/relation extraction LLM calls whose outputs are much
# shorter than the input episode.  0.30 is a reasonable conservative estimate.
_GRAPHITI_OUTPUT_RATIO = 0.30


class GraphClient:
    _client = None

    @classmethod
    def get_client(cls) -> Graphiti:
        """
        Returns (or lazily creates) the Graphiti singleton.
        NOTE: must be called before or outside the async event loop if the
        Neo4j driver performs synchronous init.  In practice this is fine
        because it is called at the start of run_poc.py's `ensure_schema`.
        """
        if cls._client is not None:
            return cls._client

        provider = settings.LLM_PROVIDER.lower()
        try:
            if provider == "gemini":
                from agent.gemini_client import GeminiClient
                from graphiti_core.embedder.gemini import GeminiEmbedder

                logger.info("Initializing Graphiti with Gemini…")
                llm_client = GeminiClient(model_name=settings.DEFAULT_MODEL)
                embedder = GeminiEmbedder()
                cls._client = Graphiti(
                    uri=settings.NEO4J_URI,
                    user=settings.NEO4J_USER,
                    password=settings.NEO4J_PASSWORD,
                    llm_client=llm_client,
                    embedder=embedder,
                )
            else:
                from graphiti_core.llm_client.config import LLMConfig
                from graphiti_core.llm_client.openai_client import OpenAIClient

                logger.info("Initializing Graphiti with OpenAI (%s)…", settings.DEFAULT_MODEL)
                llm_config = LLMConfig(
                    api_key=settings.OPENAI_API_KEY,
                    model=settings.DEFAULT_MODEL,
                )
                llm_client = OpenAIClient(config=llm_config)
                cls._client = Graphiti(
                    uri=settings.NEO4J_URI,
                    user=settings.NEO4J_USER,
                    password=settings.NEO4J_PASSWORD,
                    llm_client=llm_client,
                )

            logger.info("Graphiti client initialized (provider=%s).", provider)
        except Exception:
            logger.exception("Failed to initialize Graphiti client")
            raise

        return cls._client

    @classmethod
    async def ensure_schema(cls) -> None:
        """Creates necessary Neo4j indices / constraints if they don't exist."""
        client = cls.get_client()
        try:
            await client.driver.execute_query(
                """
                CREATE FULLTEXT INDEX node_name_and_summary IF NOT EXISTS
                FOR (n:Entity)
                ON EACH [n.name, n.summary]
                """
            )
            await client.driver.execute_query(
                """
                CREATE CONSTRAINT entity_uuid IF NOT EXISTS
                FOR (n:Entity) REQUIRE n.uuid IS UNIQUE
                """
            )
            logger.info("Graphiti Neo4j schema/indices ensured.")
        except Exception:
            logger.exception("Failed to ensure Graphiti schema — continuing anyway")

    @classmethod
    async def add_episode(cls, content: str, source_reference: str) -> None:
        """Adds an episode to the knowledge graph and tracks estimated cost."""
        client = cls.get_client()

        estimated_input = tracker.estimate_tokens(content)
        # FIXED: use a UUID-based op_id to avoid collision under concurrency
        op_id = f"graph_ingest_{uuid.uuid4().hex}"
        tracker.start_operation(op_id, "graph_ingestion")

        try:
            from graphiti_core.nodes import EpisodeType

            await client.add_episode(
                name=source_reference,
                episode_body=content,
                source_description=f"Ingestion from {source_reference}",
                reference_time=datetime.now(),
                source=EpisodeType.text,
            )

            # FIXED: more realistic output estimate (was // 2 = 50 %, now 30 %)
            estimated_output = int(estimated_input * _GRAPHITI_OUTPUT_RATIO)
            tracker.record_usage(
                op_id,
                estimated_input,
                estimated_output,
                settings.DEFAULT_MODEL,
                "graphiti_add_episode",
            )

        except Exception:
            logger.exception("Error adding episode to graph (%s)", source_reference)
            raise
        finally:
            metrics = tracker.end_operation(op_id)
            if metrics:
                logger.info(
                    "Graph ingestion %s: est. cost $%.4f", source_reference, metrics.cost_usd
                )

    @classmethod
    async def search(cls, query: str) -> List[str]:
        """Searches the knowledge graph and returns result strings."""
        client = cls.get_client()
        results = await client.search(query)
        return [str(r) for r in results] if results else []