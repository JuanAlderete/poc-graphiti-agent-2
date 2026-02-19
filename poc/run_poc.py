import asyncio
import argparse
import logging
import time
from poc.check_system import check_connections
from ingestion.ingest import ingest_directory
from agent.tools import vector_search_tool, graph_search_tool, hybrid_search_tool
from poc.queries import TEST_QUERIES
from poc.content_generator import get_content_generator
from poc.prompts import email, historia, reel_cta, reel_lead_magnet
from agent.graph_utils import GraphClient


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/poc_execution.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

async def run_ingestion(directory: str, skip_graphiti: bool = False):
    logger.info(f"Starting ingestion from {directory} (Skip Graphiti: {skip_graphiti})...")
    
    if not skip_graphiti:
        logger.info("Ensuring Graphiti schema indices...")
        await GraphClient.ensure_schema()
        
    await ingest_directory(directory, skip_graphiti=skip_graphiti)

    logger.info("Ingestion complete.")


async def run_search_tests(skip_graphiti: bool = False):
    logger.info(f"Starting search tests (skip_graphiti={skip_graphiti})...")
    
    for q in TEST_QUERIES:
        q_text = q["text"]
        q_type = q["type"]
        q_id = q["id"]
        
        # Skip reasoning
        if skip_graphiti and (q_type == "graph" or q_type == "hybrid"):
            # logger.info(f"Skipping Query {q_id} ({q_type}) due to skip_graphiti")
            continue

        try:
            logger.info(f"Running Query {q_id} ({q_type}): {q_text}")
            if q_type == "vector":
                await vector_search_tool(q_text)
            elif q_type == "graph":
                await graph_search_tool(q_text)
            elif q_type == "hybrid":
                await hybrid_search_tool(q_text)
            else:
                logger.warning(f"Unknown query type: {q_type}")
        except Exception as e:
            logger.error(f"Error in query {q_id}: {e}")

    logger.info("Search tests complete.")


async def run_generation_tests():
    logger.info("Starting generation tests...")
    generator = get_content_generator()
    
    # 1. Email
    logger.info("Generating Email...")
    email_prompt = email.PROMPT_TEMPLATE.format(
        topic="SaaS Growth",
        context="Contexto simulado sobre crecimiento B2B...",
        objective="Agendar una demo"
    )
    email_content = await generator.generate(email_prompt, email.SYSTEM_PROMPT)
    print(f"\n--- EMAIL CONTENT ---\n{email_content}\n---------------------\n")
    
    # 2. Historia
    logger.info("Generating Historia...")
    historia_prompt = historia.PROMPT_TEMPLATE.format(
        topic="El origen de una startup",
        context="Fundadores en un garaje...",
        tone="Inspirador"
    )
    historia_content = await generator.generate(historia_prompt, historia.SYSTEM_PROMPT)
    print(f"\n--- STORITELLING CONTENT ---\n{historia_content}\n----------------------------\n")
    
    # 3. Reel CTA
    logger.info("Generating Reel CTA...")
    cta_prompt = reel_cta.PROMPT_TEMPLATE.format(
        topic="Productivity Hacks",
        context="Uso de herramientas AI...",
        cta="Sígueme para más"
    )
    cta_content = await generator.generate(cta_prompt, reel_cta.SYSTEM_PROMPT)
    print(f"\n--- REEL CTA CONTENT ---\n{cta_content}\n------------------------\n")

    logger.info("Generation tests complete.")


async def main():
    parser = argparse.ArgumentParser(description="Run Graphiti POC")
    parser.add_argument("--skip-checks", action="store_true", help="Skip system health checks")
    parser.add_argument("--ingest", type=str, help="Directory to ingest docs from")
    parser.add_argument("--search", action="store_true", help="Run search tests")
    parser.add_argument("--generate", action="store_true", help="Run generation tests")
    parser.add_argument("--all", action="store_true", help="Run all phases")
    parser.add_argument("--skip-graphiti", action="store_true", help="Skip Graphiti ingestion (Postgres only)")
    parser.add_argument("--clear-logs", action="store_true", help="Clear all CSV logs before running")
    parser.add_argument("--clear-db", action="store_true", help="Clear Postgres database (documents & chunks) before running")
    
    args = parser.parse_args()
    
    if not args.skip_checks:
        if not await check_connections():
            logger.error("System checks failed. Exiting.")
            return

    if args.clear_logs:
        from poc.logging_utils import clear_all_logs
        logger.info("Clearing all CSV logs...")
        clear_all_logs()
        # Also clear the execution log if possible, though we are writing to it right now.
        # We'll just leave poc_execution.log as it captures this run's info.

    if args.clear_db:
        from agent.db_utils import DatabasePool
        logger.info("Clearing Postgres database (documents, chunks)...")
        await DatabasePool.clear_database()



    if args.ingest or args.all:
        if args.ingest:
            await run_ingestion(args.ingest, skip_graphiti=args.skip_graphiti)

        elif args.all:
            # Default doc path if --all used without --ingest?
            # Or assume user passes --ingest with --all if they want ingestion
            if args.ingest:
                 await run_ingestion(args.ingest)
            else:
                logger.info("Skipping ingestion (no directory provided).")

    if args.search or args.all:
        await run_search_tests(skip_graphiti=args.skip_graphiti)


    if args.generate or args.all:
        await run_generation_tests()

if __name__ == "__main__":
    asyncio.run(main())
