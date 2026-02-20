import logging
import uuid
from datetime import datetime
from typing import List, Optional

from graphiti_core import Graphiti

from agent.config import settings
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)

_GRAPHITI_OUTPUT_RATIO = 0.30  # ratio conservador tokens-out / tokens-in


class GraphClient:
    _client: Optional[Graphiti] = None
    _initialized: bool = False  # Flag: build_indices_and_constraints ya fue llamado

    @classmethod
    def _build_client(cls) -> Graphiti:
        """
        Construye el objeto Graphiti de forma síncrona.
        NO llama build_indices_and_constraints — eso se hace en ensure_initialized().
        """
        provider = settings.LLM_PROVIDER.lower()
        try:
            if provider == "gemini":
                from agent.gemini_client import GeminiClient
                from graphiti_core.embedder.gemini import GeminiEmbedder
                logger.info("Initializing Graphiti with Gemini (%s)…", settings.DEFAULT_MODEL)
                client = Graphiti(
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
                client = Graphiti(
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
            logger.info("Graphiti client object created (provider=%s).", provider)
            return client
        except Exception:
            logger.exception("Failed to build Graphiti client")
            raise

    @classmethod
    async def ensure_initialized(cls) -> Graphiti:
        """
        Retorna el cliente Graphiti listo para usar.

        La primera vez:
          1. Construye el objeto Graphiti.
          2. Llama build_indices_and_constraints() — crea índices y constraints
             en Neo4j necesarios para que add_episode() funcione.

        Las siguientes veces retorna el cliente cacheado directamente.
        """
        if cls._client is None:
            cls._client = cls._build_client()

        if not cls._initialized:
            try:
                logger.info("Running build_indices_and_constraints() on Neo4j…")
                await cls._client.build_indices_and_constraints()
                cls._initialized = True
                logger.info("Graphiti indices/constraints ready.")
            except Exception:
                logger.exception(
                    "build_indices_and_constraints() failed. "
                    "Neo4j may not be running or credentials are wrong."
                )
                raise

        return cls._client

    @classmethod
    async def ensure_schema(cls) -> None:
        """
        Alias público para mantener compatibilidad con run_poc.py y hydrate_graph.py.
        Delega en ensure_initialized().
        """
        await cls.ensure_initialized()

    @classmethod
    async def add_episode(
        cls,
        content: str,
        source_reference: str,
        source_description: Optional[str] = None,
    ) -> None:
        """
        Añade un episodio al knowledge graph.

        `source_description` guía al LLM de Graphiti hacia las entidades correctas.
        Si se provee el `graphiti_ready_context` calculado en Fase 1 (ingesta),
        Graphiti extrae entidades más precisas con menos tokens.
        """
        client = await cls.ensure_initialized()

        estimated_input = tracker.estimate_tokens(content)
        op_id = f"graph_ingest_{uuid.uuid4().hex}"
        tracker.start_operation(op_id, "graph_ingestion")

        effective_description = source_description or f"Document ingested from {source_reference}"

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
                    "Graph episode '%s': est. cost $%.4f (in=%d out=%d tokens)",
                    source_reference,
                    metrics.cost_usd,
                    metrics.tokens_in,
                    metrics.tokens_out,
                )

    @classmethod
    async def search(cls, query: str, num_results: int = 5) -> List[str]:
        """
        Busca en el knowledge graph y retorna resultados como strings.

        graphiti-core 0.12.x retorna una lista de objetos (EntityEdge, etc.).
        Los serializamos con str() para mantener la interfaz simple.
        """
        client = await cls.ensure_initialized()
        try:
            results = await client.search(query, num_results=num_results)
            if not results:
                return []
            # Normalizar: graphiti puede retornar varios tipos de objeto
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
            logger.exception("Graph search failed for query: %s", query)
            return []

    @classmethod
    def reset(cls) -> None:
        """
        Resetea el singleton. Útil en tests o cuando cambia la config.
        """
        cls._client = None
        cls._initialized = False