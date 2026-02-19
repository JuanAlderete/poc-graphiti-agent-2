from agent.db_utils import vector_search, hybrid_search
from agent.graph_utils import GraphClient
from agent.models import SearchResult
from poc.token_tracker import tracker
from poc.logging_utils import search_logger
from agent.config import settings
import time
import logging
import json
from typing import List, Dict, Any


logger = logging.getLogger(__name__)

async def vector_search_tool(query: str, limit: int = 5) -> List[SearchResult]:
    """
    Performs a vector search and logs metrics.
    """
    start_time = time.time()
    op_id = f"search_vector_{int(start_time*1000)}"
    tracker.start_operation(op_id, "vector_search")
    
    # Estimate input tokens
    tokens_in = tracker.estimate_tokens(query)
    
    # Mock embedding generation cost/tokens (since it happens inside db_utils or we should call embedder)
    # Ideally, we call embedder here to get embedding, then pass to db_utils.
    # We will assume db_utils handles it or we should refactor.
    # For this POC, let's assume we use the embedder from ingestion (circular dependency risk, but okay for POC)
    from ingestion.embedder import EmbeddingGenerator
    embedder = EmbeddingGenerator()
    embedding, embed_tokens = await embedder.generate_embedding(query)
    
    tracker.record_usage(op_id, tokens_in, 0, settings.EMBEDDING_MODEL, "embedding_generation")
    
    results = await vector_search(embedding, limit)
    
    latency_ms = (time.time() - start_time) * 1000
    
    # Log to CSV
    # Calculate total costs
    metrics = tracker.end_operation(op_id)
    cost = metrics.cost_usd if metrics else 0.0
    
    search_logger.log_row({
        "query_id": op_id,
        "timestamp": start_time,
        "query_texto": query,
        "longitud_query": len(query),
        "tipo_busqueda": "vector",
        "tokens_embedding": embed_tokens,
        "tokens_llm_in": 0,
        "tokens_llm_out": 0,
        "costo_embedding_usd": cost, # Simplified
        "costo_llm_usd": 0,
        "costo_total_usd": cost,
        "resultados_retornados": len(results),
        "latencia_ms": latency_ms
    })
    
    return [
        SearchResult(
            content=r['content'], 
            metadata=json.loads(r['metadata']) if isinstance(r['metadata'], str) else r['metadata'], 
            score=r['score'], 
            source="postgres"
        ) for r in results
    ]


async def graph_search_tool(query: str) -> List[SearchResult]:
    """
    Performs a graph search and logs metrics.
    """
    start_time = time.time()
    op_id = f"search_graph_{int(start_time*1000)}"
    tracker.start_operation(op_id, "graph_search")
    
    tokens_in = tracker.estimate_tokens(query)
    
    # Graph search via Graphiti
    results_text = await GraphClient.search(query)
    
    # Estimate output tokens
    tokens_out = sum(tracker.estimate_tokens(t) for t in results_text)
    
    # Record LLM usage in graph search (if Graphiti uses LLM for search, which it does)
    # We assume 'gpt-4o-mini' for graph search internal reasoning
    tracker.record_usage(op_id, tokens_in, tokens_out, settings.DEFAULT_MODEL, "graph_search_llm")
    
    latency_ms = (time.time() - start_time) * 1000
    
    metrics = tracker.end_operation(op_id)
    cost = metrics.cost_usd if metrics else 0.0
    
    search_logger.log_row({
        "query_id": op_id,
        "timestamp": start_time,
        "query_texto": query,
        "longitud_query": len(query),
        "tipo_busqueda": "graph",
        "tokens_embedding": 0,
        "tokens_llm_in": tokens_in,
        "tokens_llm_out": tokens_out,
        "costo_embedding_usd": 0,
        "costo_llm_usd": cost,
        "costo_total_usd": cost,
        "resultados_retornados": len(results_text),
        "latencia_ms": latency_ms
    })
    
    return [SearchResult(content=t, source="graphiti") for t in results_text]

async def hybrid_search_tool(query: str, limit: int = 5) -> List[SearchResult]:
    """
    Combines vector and text search using Postgres RRF function.
    """
    start_time = time.time()
    op_id = f"search_hybrid_{int(start_time*1000)}"
    tracker.start_operation(op_id, "hybrid_search")
    
    # Estimate input tokens
    tokens_in = tracker.estimate_tokens(query)
    
    # 1. Get Embedding (needed for vector part of hybrid)
    from ingestion.embedder import EmbeddingGenerator
    embedder = EmbeddingGenerator()
    embedding, embed_tokens = await embedder.generate_embedding(query)
    
    tracker.record_usage(op_id, tokens_in, 0, settings.EMBEDDING_MODEL, "embedding_generation")
    
    # 2. Execute Hybrid Search
    results = await hybrid_search(query, embedding, limit)
    
    latency_ms = (time.time() - start_time) * 1000
    
    metrics = tracker.end_operation(op_id)
    cost = metrics.cost_usd if metrics else 0.0
    
    search_logger.log_row({
        "query_id": op_id,
        "timestamp": start_time,
        "query_texto": query,
        "longitud_query": len(query),
        "tipo_busqueda": "hybrid_rrf",
        "tokens_embedding": embed_tokens,
        "tokens_llm_in": 0,
        "tokens_llm_out": 0,
        "costo_embedding_usd": cost,
        "costo_llm_usd": 0,
        "costo_total_usd": cost,
        "resultados_retornados": len(results),
        "latencia_ms": latency_ms
    })
    
    return [
        SearchResult(
            content=r['content'], 
            metadata={**(json.loads(r['metadata']) if isinstance(r['metadata'], str) else r['metadata']), "vector_score": r.get('vector_score'), "text_score": r.get('text_score')}, 
            score=r['score'], 
            source="postgres_hybrid"
        ) for r in results
    ]

