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


async def run_ingestion(directory: str, skip_graphiti: bool = False, max_files: int = 0) -> None:
    logger.info("Starting ingestion from '%s' (skip_graphiti=%s)…", directory, skip_graphiti)
    await ingest_directory(directory, skip_graphiti=skip_graphiti, max_files=max_files)
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


async def run_generation_with_agents(
    formato: str = "reel_cta",
    topic: str = "Validación de ideas de negocio",
    context: str = "",
    **kwargs,
) -> "AgentOutput":
    """
    Generación usando los nuevos agentes estructurados.
    Retorna AgentOutput con datos estructurados por formato.
    """
    from services.generation_service import GenerationService

    if not context:
        # Si no se pasa contexto, hacer una búsqueda híbrida para obtenerlo
        results = await hybrid_search_tool(topic, limit=3)
        context = "\n\n---\n\n".join(r.content for r in results) if results else "Sin contexto disponible."

    service = GenerationService()
    output = await service.generate(formato, topic=topic, context=context, **kwargs)

    print(f"\n{'='*50}")
    print(f"FORMATO: {output.formato.upper()}")
    print(f"TEMA: {output.topic}")
    print(f"QA: {'✅ PASSED' if output.qa_passed else '❌ FAILED'}")
    if not output.qa_passed:
        print(f"QA NOTES: {output.qa_notes}")
    print(f"COSTO: ${output.cost_usd:.4f}")
    print(f"{'='*50}")
    print("OUTPUT ESTRUCTURADO:")
    import json
    print(json.dumps(output.data, ensure_ascii=False, indent=2))
    print(f"{'='*50}\n")

    return output


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
    parser.add_argument("--generate-structured", action="store_true", help="Run generation with structured agents")
    parser.add_argument("--formato", type=str, default="reel_cta", help="Format for structured generation: reel_cta|historia|email|reel_lead_magnet|ads")
    parser.add_argument("--topic", type=str, default="Validación de ideas de negocio", help="Topic for structured generation")
    parser.add_argument("--max-files", type=int, default=0, help="Max files to ingest (0 = all)")

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
        logger.info("Clearing Neo4j graph…")
        await GraphClient.clear_graph()

    # ── Ingesta ───────────────────────────────────────────────────────────────
    # FIXED: la lógica anterior tenía un elif anidado que nunca se ejecutaba
    ingest_dir = args.ingest
    if (args.ingest or args.all) and ingest_dir:
        await run_ingestion(ingest_dir, skip_graphiti=args.skip_graphiti, max_files=args.max_files)
    elif args.all and not ingest_dir:
        logger.info("--all activado sin --ingest: saltando ingesta (no hay directorio).")

    # ── Búsquedas ─────────────────────────────────────────────────────────────
    if args.search or args.all:
        await run_search_tests(skip_graphiti=args.skip_graphiti)

    # ── Generación ────────────────────────────────────────────────────────────
    if args.generate or args.all:
        await run_generation_tests()

    # ── Generación con Agentes Estructurados ──────────────────────────────────
    if args.generate_structured:
        await run_generation_with_agents(formato=args.formato, topic=args.topic)


if __name__ == "__main__":
    asyncio.run(main())