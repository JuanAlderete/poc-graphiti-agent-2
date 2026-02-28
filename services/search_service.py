"""
Servicio de búsqueda que expone vector, graph, hybrid y el nuevo retrieval híbrido real.
HOY: llamado desde tools.py y Streamlit.
FUTURO: expuesto via FastAPI GET /search.
"""
import logging
from typing import List, Optional

from agent.models import SearchResult
from agent.tools import vector_search_with_diversity, hybrid_search
from agent.retrieval_engine import RetrievalEngine
from ingestion.embedder import get_embedder

logger = logging.getLogger(__name__)


class SearchService:
    """
    Facade sobre los diferentes modos de búsqueda.

    Uso actual (POC):
        service = SearchService()
        results = await service.search("hybrid_real", "¿Qué es PMF?")

    Uso futuro (FastAPI):
        @app.get("/search")
        async def search_endpoint(q: str, mode: str = "hybrid_real"):
            return await service.search(mode, q)
    """

    def __init__(self):
        self._retrieval_engine = RetrievalEngine()

    async def search(
        self,
        mode: str,
        query: str,
        limit: int = 3,
    ) -> List[SearchResult]:
        """
        Args:
            mode: 'vector' | 'graph' | 'hybrid' | 'hybrid_real'
                  'hybrid_real' = Neo4j → episode_id → chunks Postgres (Tarea 5)
                  'hybrid' = vector + FTS RRF en Postgres (existente)
            query: Texto de búsqueda.
            limit: Número máximo de resultados.
        """
        embedder = get_embedder()
        embedding = None
        if mode in ("vector", "hybrid"):
            embedding, _ = await embedder.generate_embedding(query)

        if mode == "vector":
            return await vector_search_with_diversity(embedding, limit=limit)
        elif mode == "graph":
            from agent.graph_utils import GraphClient
            # GraphClient.search returns a list of raw objects, we need to convert to SearchResult if missing
            # But the original search_service.py expected SearchResult. 
            # Given the requirement to adapt, let's wrap graph results or use hybrid_real
            results = await GraphClient.search(query, num_results=limit)
            return [
                SearchResult(
                    content=str(r),
                    metadata={},
                    score=0.9,
                    source="graph"
                ) for r in results
            ]
        elif mode == "hybrid":
            return await hybrid_search(query, embedding, limit=limit)
        elif mode == "hybrid_real":
            return await self._retrieval_engine.search(query, limit=limit)
        else:
            logger.warning("Unknown search mode '%s', falling back to hybrid", mode)
            if embedding is None:
                embedding, _ = await embedder.generate_embedding(query)
            return await hybrid_search(query, embedding, limit=limit)
