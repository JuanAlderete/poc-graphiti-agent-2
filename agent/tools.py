import json
import logging
import time
from typing import Any, Dict, List

from agent.config import settings
from agent.db_utils import hybrid_search, vector_search
from agent.graph_utils import GraphClient
from agent.models import SearchResult
from ingestion.embedder import get_embedder
from poc.logging_utils import search_logger
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)

# OPTIMIZED: reducido de 5 -> 3
_DEFAULT_SEARCH_LIMIT = 3


def _parse_metadata(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw or {}


def _log_search(
    op_id: str, start_time: float, query: str, search_type: str,
    embed_tokens: int, llm_in: int, llm_out: int,
    embed_cost: float, llm_cost: float, result_count: int, latency_ms: float,
) -> None:
    search_logger.log_row({
        "query_id": op_id,
        "timestamp": start_time,
        "query_texto": query,
        "longitud_query": len(query),
        "tipo_busqueda": search_type,
        "tokens_embedding": embed_tokens,
        "tokens_llm_in": llm_in,
        "tokens_llm_out": llm_out,
        "costo_embedding_usd": embed_cost,
        "costo_llm_usd": llm_cost,
        "costo_total_usd": embed_cost + llm_cost,
        "resultados_retornados": result_count,
        "latencia_ms": latency_ms,
    })


async def vector_search_tool(query: str, limit: int = _DEFAULT_SEARCH_LIMIT) -> List[SearchResult]:
    """Busqueda por similitud vectorial contra chunks en Postgres."""
    start_time = time.time()
    op_id = f"search_vector_{start_time:.3f}"
    tracker.start_operation(op_id, "vector_search")

    embedder = get_embedder()
    embedding, embed_tokens = await embedder.generate_embedding(query)
    tracker.record_usage(op_id, embed_tokens, 0, settings.EMBEDDING_MODEL, "embedding")

    results = await vector_search(embedding, limit)

    latency_ms = (time.time() - start_time) * 1000
    metrics = tracker.end_operation(op_id)
    cost = metrics.cost_usd if metrics else 0.0

    _log_search(op_id, start_time, query, "vector", embed_tokens, 0, 0, cost, 0.0, len(results), latency_ms)

    return [
        SearchResult(
            content=r["content"],
            metadata=_parse_metadata(r["metadata"]),
            score=r["score"],
            source="postgres",
        )
        for r in results
    ]


async def graph_search_tool(query: str) -> List[SearchResult]:
    """Busqueda en grafo via Graphiti / Neo4j."""
    start_time = time.time()
    op_id = f"search_graph_{start_time:.3f}"
    tracker.start_operation(op_id, "graph_search")

    tokens_in = tracker.estimate_tokens(query)
    results_text = await GraphClient.search(query)
    tokens_out = sum(tracker.estimate_tokens(t) for t in results_text)
    tracker.record_usage(op_id, tokens_in, tokens_out, settings.DEFAULT_MODEL, "graph_search_llm")

    latency_ms = (time.time() - start_time) * 1000
    metrics = tracker.end_operation(op_id)
    cost = metrics.cost_usd if metrics else 0.0

    _log_search(op_id, start_time, query, "graph", 0, tokens_in, tokens_out, 0.0, cost, len(results_text), latency_ms)

    return [SearchResult(content=t, source="graphiti") for t in results_text]


async def hybrid_search_tool(query: str, limit: int = _DEFAULT_SEARCH_LIMIT) -> List[SearchResult]:
    """Busqueda hibrida RRF: vector + full-text via Postgres."""
    start_time = time.time()
    op_id = f"search_hybrid_{start_time:.3f}"
    tracker.start_operation(op_id, "hybrid_search")

    embedder = get_embedder()
    embedding, embed_tokens = await embedder.generate_embedding(query)
    tracker.record_usage(op_id, embed_tokens, 0, settings.EMBEDDING_MODEL, "embedding")

    results = await hybrid_search(query, embedding, limit)

    latency_ms = (time.time() - start_time) * 1000
    metrics = tracker.end_operation(op_id)
    cost = metrics.cost_usd if metrics else 0.0

    _log_search(op_id, start_time, query, "hybrid_rrf", embed_tokens, 0, 0, cost, 0.0, len(results), latency_ms)

    return [
        SearchResult(
            content=r["content"],
            metadata={
                **_parse_metadata(r["metadata"]),
                "vector_score": r.get("vector_score"),
                "text_score": r.get("text_score"),
            },
            score=r["score"],
            source="postgres_hybrid",
        )
        for r in results
    ]