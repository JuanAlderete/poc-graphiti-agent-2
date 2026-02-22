import argparse
import asyncio
import logging
import os
import time

from agent.graph_utils import GraphClient
from agent.tools import graph_search_tool, hybrid_search_tool, vector_search_tool
from ingestion.ingest import ingest_directory
from poc.check_system import check_connections
from poc.content_generator import get_content_generator
from poc.prompts import email, historia, reel_cta, reel_lead_magnet
from poc.queries import TEST_QUERIES

# Asegurar que el directorio de logs existe antes de configurar el FileHandler
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/poc_execution.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


async def run_ingestion(directory: str, skip_graphiti: bool = False) -> None:
    logger.info("Starting ingestion from '%s' (skip_graphiti=%s)…", directory, skip_graphiti)
    # FIXED: no llamamos ensure_schema() aquí — ingest_directory() ya lo hace
    # internamente cuando skip_graphiti=False. ensure_initialized() es idempotente
    # pero quitamos la llamada redundante para mayor claridad.
    await ingest_directory(directory, skip_graphiti=skip_graphiti)
    logger.info("Ingestion complete.")


async def run_search_tests(skip_graphiti: bool = False) -> None:
    logger.info("Starting search tests (skip_graphiti=%s)…", skip_graphiti)

    for q in TEST_QUERIES:
        q_text = q["text"]
        q_type = q["type"]
        q_id = q["id"]

        if skip_graphiti and q_type in ("graph", "hybrid"):
            continue

        try:
            logger.info("Query %s (%s): %s", q_id, q_type, q_text)
            if q_type == "vector":
                await vector_search_tool(q_text)
            elif q_type == "graph":
                await graph_search_tool(q_text)
            elif q_type == "hybrid":
                await hybrid_search_tool(q_text)
            else:
                logger.warning("Unknown query type: %s", q_type)
        except Exception as e:
            logger.error("Error in query %s: %s", q_id, e)

    logger.info("Search tests complete.")


async def run_generation_tests() -> None:
    logger.info("Starting generation tests…")
    generator = get_content_generator()

    tests = [
        (
            "Email",
            email.PROMPT_TEMPLATE.format(
                topic="SaaS Growth",
                context="Contexto simulado sobre crecimiento B2B...",
                objective="Agendar una demo",
            ),
            email.SYSTEM_PROMPT,
        ),
        (
            "Historia",
            historia.PROMPT_TEMPLATE.format(
                topic="El origen de una startup",
                context="Fundadores en un garaje...",
                tone="Inspirador",
            ),
            historia.SYSTEM_PROMPT,
        ),
        (
            "Reel CTA",
            reel_cta.PROMPT_TEMPLATE.format(
                topic="Productivity Hacks",
                context="Uso de herramientas AI...",
                cta="Sígueme para más",
            ),
            reel_cta.SYSTEM_PROMPT,
        ),
    ]

    for name, prompt, system in tests:
        logger.info("Generating %s…", name)
        try:
            content = await generator.generate(prompt, system)
            separator = "-" * 40
            print(f"\n{separator}\n{name.upper()}\n{separator}\n{content}\n")
        except Exception as e:
            logger.error("Generation failed for %s: %s", name, e)

    logger.info("Generation tests complete.")


async def main() -> None:
    try:
        await _main()
    except Exception as e:
        # Detect billing quota exhaustion (distinct from transient 429 rate limits)
        code = getattr(e, "code", None)
        is_quota = code == "insufficient_quota" or (
            "insufficient_quota" in str(e)
        )
        if is_quota:
            logger.critical(
                "\n"
                "========================================================\n"
                "  FATAL ERROR: OpenAI quota exceeded (insufficient_quota)\n"
                "  Your account has no remaining credits.\n"
                "  Top up at: https://platform.openai.com/account/billing\n"
                "========================================================"
            )
            raise SystemExit(1)
        raise


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Run Graphiti POC")
    parser.add_argument("--skip-checks", action="store_true", help="Skip health checks")
    parser.add_argument("--ingest", type=str, help="Directory to ingest docs from")
    parser.add_argument("--search", action="store_true", help="Run search tests")
    parser.add_argument("--generate", action="store_true", help="Run generation tests")
    parser.add_argument("--all", action="store_true", help="Run all phases")
    parser.add_argument("--skip-graphiti", action="store_true", help="Skip Graphiti (Postgres only)")
    parser.add_argument("--clear-logs", action="store_true", help="Clear CSV logs before running")
    parser.add_argument("--clear-db", action="store_true", help="Clear Postgres DB before running")

    args = parser.parse_args()

    # ── Health check ──────────────────────────────────────────────────────────
    if not args.skip_checks:
        if not await check_connections():
            logger.error("System checks failed. Exiting.")
            return

    # ── Limpieza opcional ─────────────────────────────────────────────────────
    if args.clear_logs:
        from poc.logging_utils import clear_all_logs
        logger.info("Clearing all CSV logs…")
        clear_all_logs()

    if args.clear_db:
        from agent.db_utils import DatabasePool
        logger.info("Clearing Postgres database…")
        await DatabasePool.clear_database()
        # También resetear el cliente Graphiti para que reinicialice los índices
        GraphClient.reset()

    # ── Ingesta ───────────────────────────────────────────────────────────────
    # FIXED: la lógica anterior tenía un elif anidado que nunca se ejecutaba
    ingest_dir = args.ingest
    if (args.ingest or args.all) and ingest_dir:
        await run_ingestion(ingest_dir, skip_graphiti=args.skip_graphiti)
    elif args.all and not ingest_dir:
        logger.info("--all activado sin --ingest: saltando ingesta (no hay directorio).")

    # ── Búsquedas ─────────────────────────────────────────────────────────────
    if args.search or args.all:
        await run_search_tests(skip_graphiti=args.skip_graphiti)

    # ── Generación ────────────────────────────────────────────────────────────
    if args.generate or args.all:
        await run_generation_tests()


if __name__ == "__main__":
    asyncio.run(main())