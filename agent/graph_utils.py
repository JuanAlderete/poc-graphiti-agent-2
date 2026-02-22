import logging
import uuid
from datetime import datetime
from typing import List, Optional

from graphiti_core import Graphiti

from agent.config import settings
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)

_GRAPHITI_OUTPUT_RATIO = 0.30  # estimacion conservadora de tokens out/in

# Group ID por defecto para que todos los episodios sean recuperables juntos.
# Graphiti filtra por group_id: si cada doc tiene un grupo distinto (o None),
# las busquedas solo devuelven un subconjunto.
DEFAULT_GROUP_ID = "hybrid_rag_documents"


class GraphClient:
    """
    Singleton wrapper around Graphiti.

    Provides:
    - Lazy initialization (get_client)
    - Schema setup (ensure_schema)
    - Episode ingestion with consistent group_id (add_episode)
    - Episode retrieval with group filtering (get_all_episodes)
    - Semantic search (search)
    - State reset (reset)
    """

    _client: Optional[Graphiti] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def get_client(cls) -> Graphiti:
        if cls._client is not None:
            return cls._client

        provider = settings.LLM_PROVIDER.lower()
        try:
            if provider == "gemini":
                from agent.gemini_client import GeminiClient
                from graphiti_core.embedder.gemini import GeminiEmbedder

                logger.info(
                    "Initializing Graphiti with Gemini (%s)...", settings.DEFAULT_MODEL
                )
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

                logger.info(
                    "Initializing Graphiti with OpenAI (%s)...", settings.DEFAULT_MODEL
                )
                cls._client = Graphiti(
                    uri=settings.NEO4J_URI,
                    user=settings.NEO4J_USER,
                    password=settings.NEO4J_PASSWORD,
                    llm_client=OpenAIClient(
                        config=LLMConfig(
                            api_key=settings.OPENAI_API_KEY,
                            model=settings.DEFAULT_MODEL,
                        )
                    ),
                )
            logger.info("Graphiti client ready (provider=%s).", provider)
        except Exception:
            logger.exception("Failed to initialize Graphiti client")
            raise

        return cls._client

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton so the next call to get_client() re-creates it."""
        cls._client = None

    @classmethod
    def _build_client(cls) -> Graphiti:
        """Alias used by check_system.py health-check."""
        return cls.get_client()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

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
            logger.exception("Schema setup failed -- continuing anyway")

    # ------------------------------------------------------------------
    # Episodes
    # ------------------------------------------------------------------

    @classmethod
    async def add_episode(
        cls,
        content: str,
        source_reference: str,
        source_description: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> None:
        """
        Add an episode to the knowledge graph.

        Args:
            content: Raw text of the episode.
            source_reference: Identifier (e.g. filename).
            source_description: Pre-computed context for Graphiti.
                When hydrate_graph.py provides ``graphiti_ready_context``,
                Graphiti can skip its own classification prompt and focus
                extraction on the entities already identified, saving ~20-30 %
                of tokens per episode.
            group_id: Logical group for filtering. Defaults to
                ``DEFAULT_GROUP_ID`` so all documents are retrievable together.
        """
        client = cls.get_client()
        estimated_input = tracker.estimate_tokens(content)
        op_id = f"graph_ingest_{uuid.uuid4().hex}"
        tracker.start_operation(op_id, "graph_ingestion")

        effective_description = source_description or f"Ingestion from {source_reference}"
        effective_group = group_id if group_id is not None else DEFAULT_GROUP_ID

        try:
            from graphiti_core.nodes import EpisodeType

            await client.add_episode(
                name=source_reference,
                episode_body=content,
                source_description=effective_description,
                reference_time=datetime.now(),
                source=EpisodeType.text,
                group_id=effective_group,
            )
            estimated_output = int(estimated_input * _GRAPHITI_OUTPUT_RATIO)
            tracker.record_usage(
                op_id,
                estimated_input,
                estimated_output,
                settings.DEFAULT_MODEL,
                "graphiti_add_episode",
            )
        except Exception:
            logger.exception("Error adding episode (%s)", source_reference)
            raise
        finally:
            metrics = tracker.end_operation(op_id)
            if metrics:
                logger.info(
                    "Graph episode %s: est. cost $%.4f",
                    source_reference,
                    metrics.cost_usd,
                )

    @classmethod
    async def get_all_episodes(
        cls,
        group_ids: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[dict]:
        """
        Retrieve episodes from the graph.

        Args:
            group_ids: Filter by these groups. ``None`` returns episodes from
                ALL groups — this is the key fix so that all documents appear,
                not just one.
            limit: Maximum number of episodes to return.
        """
        client = cls.get_client()

        try:
            episodes = await client.get_episodes(
                group_ids=group_ids,
                limit=limit,
            )

            logger.info("Retrieved %d episodes", len(episodes))

            result = []
            for ep in episodes:
                result.append(
                    {
                        "uuid": str(ep.uuid),
                        "name": ep.name,
                        "content": (
                            ep.content
                            if hasattr(ep, "content")
                            else ep.episode_body
                        ),
                        "group_id": ep.group_id,
                        "created_at": (
                            ep.created_at.isoformat() if ep.created_at else None
                        ),
                        "source": (
                            ep.source.value
                            if hasattr(ep.source, "value")
                            else str(ep.source)
                        ),
                    }
                )
            return result
        except Exception:
            logger.exception("Error retrieving episodes")
            raise

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    @classmethod
    async def search(cls, query: str) -> List[str]:
        client = cls.get_client()
        results = await client.search(query)
        return [str(r) for r in results] if results else []