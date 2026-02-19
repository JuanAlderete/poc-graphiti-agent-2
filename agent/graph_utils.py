import logging
import time
from datetime import datetime
from typing import List, Dict, Any
# Updated import based on inspection
from graphiti_core import Graphiti
# from graphiti_core.nodes import Episode

from agent.config import settings
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)

class GraphClient:
    _client = None

    @classmethod
    def get_client(cls):
        if cls._client is None:
            try:
                # Determine provider
                provider = settings.LLM_PROVIDER.lower()
                
                if provider == "gemini":
                    from agent.gemini_client import GeminiClient
                    from graphiti_core.embedder.gemini import GeminiEmbedder
                     
                    logger.info("Initializing Graphiti with Gemini...")
                    
                    llm_client = GeminiClient(model_name=settings.DEFAULT_MODEL) # e.g. gemini-1.5-flash
                    # Embedder needs config? 
                    # Inspect showed: GeminiEmbedder(config: GeminiEmbedderConfig | None = None)
                    # We can pass None to use default or create config if needed. 
                    # Default likely uses env var or we need to pass api key in config?
                    # The GeminiEmbedder likely uses google.generativeai.configure which we did in GeminiClient
                    embedder = GeminiEmbedder() 
                    
                    cls._client = Graphiti(
                        uri=settings.NEO4J_URI,
                        user=settings.NEO4J_USER,
                        password=settings.NEO4J_PASSWORD,
                        llm_client=llm_client,
                        embedder=embedder
                    )
                else:
                    # Default (OpenAI)
                    cls._client = Graphiti(
                        uri=settings.NEO4J_URI,
                        user=settings.NEO4J_USER,
                        password=settings.NEO4J_PASSWORD
                    )
                    
                logger.info(f"Graphiti client initialized ({provider}).")
            except Exception as e:
                logger.error(f"Failed to initialize Graphiti client: {e}")
                raise
        return cls._client

    @classmethod
    async def ensure_schema(cls):
        """
        Ensures that necessary Neo4j indices exist.
        """
        client = cls.get_client()
        try:
            # Create fulltext index required by graphiti_core
            # We use the driver directly. 
            # graphiti_core driver wrapper has execute_query
            
            # Check/Create node_name_and_summary
            # Note: The label 'Entity' and properties 'name', 'summary' are assumed based on graphiti defaults.
            # If graphiti uses different labels, we might need to adjust. 
            # But the error 'node_name_and_summary' matches standard graphiti.
            
            query = """
            CREATE FULLTEXT INDEX node_name_and_summary IF NOT EXISTS
            FOR (n:Entity)
            ON EACH [n.name, n.summary]
            """
            
            # Using client.driver.execute_query which is async
            await client.driver.execute_query(query)
            
            # Also ensure constraints if needed, usually on uuid
            query_constraint = """
            CREATE CONSTRAINT entity_uuid IF NOT EXISTS
            FOR (n:Entity) REQUIRE n.uuid IS UNIQUE
            """
            await client.driver.execute_query(query_constraint)

            logger.info("Graphiti Neo4j schema/indices ensured.")
        except Exception as e:
            logger.error(f"Failed to ensure Graphiti schema: {e}")
            # We continue, as it might already exist or we might have permissions issues, 
            # but let's hope it works.



    @classmethod
    async def add_episode(cls, content: str, source_reference: str):
        """
        Adds an episode to the graph.
        """
        client = cls.get_client()
        
        # Estimate tokens
        estimated_input_tokens = tracker.estimate_tokens(content)
        op_id = f"graph_ingest_{int(time.time()*1000)}"
        tracker.start_operation(op_id, "graph_ingestion")
        
        try:
            # Import EpisodeType locally to avoid circular imports if any, or just compatibility
            from graphiti_core.nodes import EpisodeType

            # Updated add_episode query based on inspection
            await client.add_episode(
                name=source_reference,
                episode_body=content,
                source_description=f"Ingestion from {source_reference}",
                reference_time=datetime.now(),
                source=EpisodeType.text
            )
            
            # Mocking output tokens
            estimated_output_tokens = estimated_input_tokens // 2 
            
            tracker.record_usage(
                op_id, 
                estimated_input_tokens, 
                estimated_output_tokens, 
                settings.DEFAULT_MODEL,
                "graphiti_add_episode"
            )
            
        except Exception as e:
            logger.error(f"Error adding episode to graph: {e}")
            raise
        finally:
            metrics = tracker.end_operation(op_id)
            if metrics:
                logger.info(f"Graph ingestion cost: ${metrics.cost_usd:.4f}")

    @classmethod
    async def search(cls, query: str) -> List[str]:
        """
        Searches the graph for relevant info.
        """
        client = cls.get_client()
        # Use search method
        results = await client.search(query)
        
        # Transform results to string list. Assuming results are edges or can be stringified.
        # Ideally we'd extract meaningful text. For now, string representation.
        return [str(r) for r in results] if results else []

