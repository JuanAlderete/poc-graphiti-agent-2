"""
api/main.py
-----------
Entry point de la aplicación FastAPI — MarketingMaker AI Engine.

Arranca con:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

O desde Docker:
    docker compose up api
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.db_utils import DatabasePool
from poc.config import config

# Configurar logging antes de importar los routers
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# LIFESPAN — startup y shutdown
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestiona el ciclo de vida de la aplicación.
    - Startup: inicializa el pool de Postgres y crea las tablas si no existen.
    - Shutdown: cierra el pool de conexiones limpiamente.
    """
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info(
        "MarketingMaker AI Engine arrancando — provider=%s model=%s dims=%d env=%s",
        config.LLM_PROVIDER,
        config.DEFAULT_MODEL,
        config.EMBEDDING_DIMS,
        config.ENVIRONMENT,
    )

    try:
        await DatabasePool.init_db()
        logger.info("Postgres inicializado correctamente")
    except Exception as e:
        logger.error("Error inicializando Postgres: %s", e)
        # No fallar el startup — el health check reportará el error

    if config.ENABLE_GRAPH:
        try:
            from agent.graph_utils import GraphClient
            await GraphClient.ensure_schema()
            logger.info("Neo4j inicializado correctamente")
        except Exception as e:
            logger.warning("Neo4j no disponible (ENABLE_GRAPH=true pero falló): %s", e)

    logger.info("API lista en http://0.0.0.0:%s", os.getenv("API_PORT", "8000"))

    yield  # ← La app corre aquí

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Cerrando MarketingMaker AI Engine...")
    await DatabasePool.close()
    logger.info("Pool de Postgres cerrado. Bye!")


# =============================================================================
# APP
# =============================================================================

app = FastAPI(
    title="MarketingMaker AI Engine",
    description=(
        "Sistema de generación automatizada de contenido semanal. "
        "Ingesta transcripciones → genera reels, historias, emails y ads → publica en Notion."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",      # Swagger UI en /docs
    redoc_url="/redoc",    # ReDoc en /redoc
    openapi_url="/openapi.json",
)


# =============================================================================
# MIDDLEWARE
# =============================================================================

# CORS — ajustar origins en producción
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if config.ENVIRONMENT == "development" else [
        "https://n8n.tudominio.com",
        "https://tu-dashboard.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# =============================================================================
# ROUTERS
# =============================================================================

from api.routes.health import router as health_router
from api.routes.ingest import router as ingest_router
from api.routes.generate import router as generate_router
from api.routes.config_check import router as config_check_router

app.include_router(health_router)
app.include_router(ingest_router)
app.include_router(generate_router)
app.include_router(config_check_router)


# =============================================================================
# ROOT
# =============================================================================

@app.get("/", tags=["Sistema"], include_in_schema=False)
async def root():
    return {
        "name":    "MarketingMaker AI Engine",
        "version": "1.0.0",
        "docs":    "/docs",
        "health":  "/health",
        "provider": config.LLM_PROVIDER,
        "model":    config.DEFAULT_MODEL,
    }