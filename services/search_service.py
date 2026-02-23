"""
Servicio de búsqueda que expone vector, graph, hybrid y el nuevo retrieval híbrido real.
HOY: llamado desde tools.py y Streamlit.
FUTURO: expuesto via FastAPI GET /search.
"""
import logging
from typing import List, Optional

from agent.models import SearchResult
from agent.tools import vector_search_tool, graph_search_tool, hybrid_search_tool
from agent.retrieval_engine import RetrievalEngine

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
        if mode == "vector":
            return await vector_search_tool(query, limit=limit)
        elif mode == "graph":
            return await graph_search_tool(query)
        elif mode == "hybrid":
            return await hybrid_search_tool(query, limit=limit)
        elif mode == "hybrid_real":
            return await self._retrieval_engine.search(query, limit=limit)
        else:
            logger.warning("Unknown search mode '%s', falling back to hybrid", mode)
            return await hybrid_search_tool(query, limit=limit)
