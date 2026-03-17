"""
api/routes/health.py
--------------------
GET /health — Verifica el estado del sistema.

Usado por n8n antes de enviar archivos y por monitoring externo.
Retorna estado de Postgres, Neo4j (si está activo) y budget.
"""
import logging
from fastapi import APIRouter

from agent.db_utils import DatabasePool
from poc.budget_guard import get_budget_status
from poc.config import config

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", tags=["Sistema"])
async def health_check() -> dict:
    """
    Verifica el estado de todos los componentes del sistema.

    Retorna:
    - status: "ok" si todo funciona, "degraded" si algún componente falla
    - postgres: "ok" | "error"
    - neo4j: "ok" | "disabled" | "error"
    - llm_provider: proveedor activo (openai | ollama | gemini)
    - budget: resumen del presupuesto mensual
    """
    result: dict = {
        "status": "ok",
        "postgres": "unknown",
        "neo4j": "disabled",
        "llm_provider": config.LLM_PROVIDER,
        "embedding_model": config.EMBEDDING_MODEL,
        "embedding_dims": config.EMBEDDING_DIMS,
        "budget": {},
    }

    # ── Postgres ──────────────────────────────────────────────────────────────
    try:
        pool = await DatabasePool.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        result["postgres"] = "ok"
    except Exception as e:
        logger.error("Health check: Postgres falló: %s", e)
        result["postgres"] = f"error: {str(e)[:100]}"
        result["status"] = "degraded"

    # ── Neo4j (solo si ENABLE_GRAPH=true) ─────────────────────────────────────
    if config.ENABLE_GRAPH:
        try:
            from agent.graph_utils import GraphClient
            client = GraphClient.get_client()
            # Ping mínimo: ejecutar una query simple
            async with client.driver.session(database="neo4j") as session:
                await session.run("RETURN 1")
            result["neo4j"] = "ok"
        except Exception as e:
            logger.error("Health check: Neo4j falló: %s", e)
            result["neo4j"] = f"error: {str(e)[:100]}"
            result["status"] = "degraded"

    # ── Budget ────────────────────────────────────────────────────────────────
    try:
        result["budget"] = get_budget_status()
    except Exception as e:
        logger.warning("Health check: budget_status falló: %s", e)
        result["budget"] = {"status": "unavailable"}

    return result