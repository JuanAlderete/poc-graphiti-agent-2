import argparse
import asyncio
import logging
import os
import time

from agent.graph_utils import GraphClient
from agent.tools import vector_search_with_diversity, hybrid_search
from ingestion.embedder import get_embedder
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
    embedder = get_embedder()

    for q in TEST_QUERIES:
        q_text = q["text"]
        q_type = q["type"]
        q_id = q["id"]

        if skip_graphiti and q_type in ("graph", "hybrid"):
            continue

        try:
            logger.info("Query %s (%s): %s", q_id, q_type, q_text)
            
            # Generate embedding for vector/hybrid searches
            embedding = None
            if q_type in ("vector", "hybrid"):
                embedding, _ = await embedder.generate_embedding(q_text)

            if q_type == "vector":
                await vector_search_with_diversity(embedding)
            elif q_type == "graph":
                await GraphClient.search(q_text)
            elif q_type == "hybrid":
                await hybrid_search(q_text, embedding)
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
    push_to_notion: bool = False,
    **kwargs,
) -> "AgentOutput":
    """
    Generación usando los nuevos agentes estructurados.
    Retorna AgentOutput con datos estructurados por formato.
    """
    from services.generation_service import GenerationService

    if not context:
        # Si no se pasa contexto, hacer una búsqueda híbrida para obtenerlo
        embedder = get_embedder()
        embedding, _ = await embedder.generate_embedding(topic)
        results = await hybrid_search(topic, embedding, limit=3)
        context = "\n\n---\n\n".join(r.content for r in results) if results else "Sin contexto disponible."

    service = GenerationService()
    output = await service.generate(formato, topic=topic, context=context, **kwargs)

    print(f"\n{'='*50}")
    print(f"FORMATO: {output.content_type.upper()}")
    print(f"QA: {'✅ PASSED' if output.qa_passed else '❌ FAILED'}")
    if not output.qa_passed:
        print(f"QA NOTES: {output.qa_reason}")
    print(f"COSTO: ${output.cost_usd:.4f}")
    print(f"{'='*50}")
    print("OUTPUT ESTRUCTURADO:")
    import json
    print(json.dumps(output.content, ensure_ascii=False, indent=2))
    print(f"{'='*50}\n")
    
    if push_to_notion:
        from storage.notion_client import NotionClient
        from datetime import date
        import time
        print(f"⏳ Empujando pieza generada a Notion ({formato})...")
        client = NotionClient()
        piece_data = output.content.copy()
        piece_data["estado"] = "Propuesta"
        piece_data["formato"] = formato
        piece_data["topico"] = topic
        piece_data["fecha_generacion"] = date.today().isoformat()
        piece_data["costo_usd"] = output.cost_usd
        piece_data["chunk_id"] = output.chunk_id or ""
        run_id = f"run-{int(time.time())}"
        piece_data.setdefault("run_id", run_id)

        page_id = await client.publish_piece(formato, piece_data)
        if page_id:
            print(f"✅ ¡Éxito! Pieza publicada en Notion. Page ID: {page_id}")
        else:
            print(f"❌ Error al publicar en Notion. Revisa los logs.")

        # Registrar el run en la DB de Weekly Runs
        qa_passed = 1 if output.qa_passed else 0
        await client.create_weekly_run(
            run_id=piece_data["run_id"],
            results_summary={
                "total":    1,
                "passed":   qa_passed,
                "failed":   1 - qa_passed,
                "cost_usd": output.cost_usd,
            }
        )
        print(f"📋 Run registrado en Weekly Runs: {piece_data['run_id']}")

    return output


async def run_notion_full_test(
    topic: str = "Validación de ideas de negocio",
) -> None:
    """
    Prueba de integración E2E: genera una pieza de cada formato y la sube a Notion.
    Todos los formatos comparten el mismo run_id.
    Al final registra un resumen consolidado en la DB de Weekly Runs.
    """
    from storage.notion_client import NotionClient
    from datetime import date
    import time

    FORMATOS = ["reel_cta", "reel_lead_magnet", "historia", "email", "ads"]
    run_id = f"test-{int(time.time())}"
    today = date.today().isoformat()
    client = NotionClient()

    total = 0
    passed_qa = 0
    failed_qa = 0
    pushed_ok = 0
    pushed_fail = 0
    total_cost = 0.0

    print(f"\n{'='*55}")
    print(f"  NOTION FULL TEST — Run ID: {run_id}")
    print(f"  Formatos: {', '.join(FORMATOS)}")
    print(f"{'='*55}\n")

    for formato in FORMATOS:
        print(f"\n--- Generando: {formato.upper()} ---")
        try:
            output = await run_generation_with_agents(
                formato=formato,
                topic=topic,
                push_to_notion=False,   # manejamos el push manualmente
            )

            total += 1
            total_cost += output.cost_usd
            if output.qa_passed:
                passed_qa += 1
            else:
                failed_qa += 1

            # Preparar y empujar a Notion
            piece_data = output.content.copy()
            piece_data["estado"] = "Propuesta"
            piece_data["formato"] = formato
            piece_data["topico"] = topic
            piece_data["fecha_generacion"] = today
            piece_data["costo_usd"] = output.cost_usd
            piece_data["chunk_id"] = output.chunk_id or ""
            piece_data.setdefault("run_id", run_id)

            page_id = await client.publish_piece(formato, piece_data)
            if page_id:
                pushed_ok += 1
                print(f"  ✅ {formato}: publicado — Page ID: {page_id}")
            else:
                pushed_fail += 1
                print(f"  ❌ {formato}: error al publicar en Notion")

        except Exception as e:
            total += 1
            failed_qa += 1
            pushed_fail += 1
            print(f"  ❌ {formato}: excepción durante generación — {e}")

    # Resumen en consola
    print(f"\n{'='*55}")
    print(f"  RESULTADOS FINALES")
    print(f"  Total formatos:   {total}")
    print(f"  QA Pasadas:       {passed_qa}")
    print(f"  QA Fallidas:      {failed_qa}")
    print(f"  Noción OK:        {pushed_ok}")
    print(f"  Notion Fallidas:  {pushed_fail}")
    print(f"  Costo total:      ${total_cost:.4f}")
    print(f"{'='*55}\n")

    # Registrar el run consolidado en Weekly Runs
    estado_run = "Completado" if pushed_fail == 0 else "Error parcial"
    await client.create_weekly_run(
        run_id=run_id,
        results_summary={
            "total":    total,
            "passed":   passed_qa,
            "failed":   failed_qa,
            "cost_usd": total_cost,
        }
    )
    print(f"📋 Run consolidado registrado en Weekly Runs (estado: {estado_run})")


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
    parser.add_argument("--generate-structured", action="store_true", help="Run generation with structured agents (legacy)")
    parser.add_argument("--generate-dry-run", action="store_true", help="Run generation natively and print (no Notion save)")
    parser.add_argument("--generate-real-run", action="store_true", help="Run generation natively and save to Notion as Propuesta")
    parser.add_argument("--test-notion-all", action="store_true", help="Genera una pieza de cada formato y la sube a Notion (test E2E completo)")
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
    if args.generate_structured or args.generate_dry_run:
        await run_generation_with_agents(formato=args.formato, topic=args.topic, push_to_notion=False)
    
    # ── Generación con Escritura en Notion (Real-Run) ─────────────────────────
    if args.generate_real_run:
        await run_generation_with_agents(formato=args.formato, topic=args.topic, push_to_notion=True)

    # ── Test E2E Completo: todos los formatos a Notion ─────────────────────
    if args.test_notion_all:
        await run_notion_full_test(topic=args.topic)


if __name__ == "__main__":
    asyncio.run(main())