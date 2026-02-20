import argparse
import asyncio
import logging
import time
from typing import Any

from agent.db_utils import (
    DatabasePool,
    get_all_documents,
    get_documents_missing_from_graph,
    mark_document_graph_ingested,
)
from agent.graph_utils import GraphClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def hydrate_graph(
    dry_run: bool = False,
    limit: int = 1000,
    reset_flags: bool = False,
) -> None:
    """
    Lee documentos de Postgres y los ingesta en Graphiti (Neo4j).

    Args:
        dry_run:     Si True, muestra qué se haría sin gastar tokens.
        limit:       Máximo de documentos a procesar.
        reset_flags: Si True, reprocesa todos los docs (ignora graph_ingested).
    """
    logger.info("=== HYDRATE GRAPH — Fase 2 ===")
    await DatabasePool.init_db()

    # ── Obtener documentos pendientes ─────────────────────────────────────────
    if reset_flags:
        logger.info("--reset-flags: fetching ALL documents regardless of graph_ingested flag.")
        docs = await get_all_documents(limit=limit)
    else:
        docs = await get_documents_missing_from_graph(limit=limit)

    if not docs:
        logger.info("✅ No hay documentos pendientes. El grafo está al día.")
        return

    logger.info("Documentos a hidratar: %d", len(docs))

    if dry_run:
        logger.info("=== DRY RUN — no se gastarán tokens ===")
        for doc in docs:
            meta = doc.get("metadata", {})
            context = meta.get("graphiti_ready_context", "[sin contexto pre-calculado]")
            people = meta.get("detected_people", [])
            companies = meta.get("detected_companies", [])
            logger.info(
                "  DOC: %s\n  CONTEXT: %s\n  People: %s | Companies: %s",
                doc["source"], context, people[:5], companies[:5],
            )
        logger.info("=== DRY RUN completado (%d docs revisados) ===", len(docs))
        return

    # ── Asegurar índices en Neo4j ─────────────────────────────────────────────
    await GraphClient.ensure_schema()

    # ── Hidratación con concurrencia controlada ───────────────────────────────
    concurrency = 3  # conservador para no spikear el rate limit del LLM
    sem = asyncio.Semaphore(concurrency)
    total_cost = 0.0
    success_count = 0
    error_count = 0
    t0 = time.time()

    async def _process_doc(doc: dict[str, Any]) -> float:
        """Procesa un único doc. Retorna costo estimado o 0.0 en error."""
        source = doc.get("title") or doc.get("source", "unknown")
        async with sem:
            try:
                meta = doc.get("metadata", {})
                if isinstance(meta, str):
                    import json
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}

                content = doc.get("content", "")
                if not content.strip():
                    logger.warning("Skipping %s — empty content.", source)
                    return 0.0

                # Usar el contexto pre-calculado en Fase 1 (el gran beneficio de esta arquitectura)
                graphiti_context = meta.get("graphiti_ready_context")

                # Log de lo que vamos a inyectar
                if graphiti_context:
                    logger.info("Hydrating: %s | Context: %s…", source, graphiti_context[:80])
                else:
                    logger.warning(
                        "Hydrating: %s | No pre-calculated context — Graphiti will infer entities "
                        "(costs more tokens). Consider re-ingesting with the new pipeline.",
                        source,
                    )

                await GraphClient.add_episode(
                    content=content,
                    source_reference=doc.get("source", source),
                    source_description=graphiti_context,
                )

                # Marcar como hidratado para no reprocesar en runs futuras
                await mark_document_graph_ingested(doc["id"])

                # Obtener costo estimado del último episodio (loggeado en graph_utils)
                # No tenemos acceso directo al costo aquí sin refactorizar más,
                # así que estimamos basándonos en el tamaño del contenido.
                from poc.token_tracker import tracker
                estimated_tokens = tracker.estimate_tokens(content)
                from poc.cost_calculator import calculate_cost
                from agent.config import settings
                cost = calculate_cost(
                    int(estimated_tokens * 1.30),  # input + 30% output
                    int(estimated_tokens * 0.30),
                    settings.DEFAULT_MODEL,
                )
                return cost

            except Exception as e:
                logger.error("Failed to hydrate %s: %s", source, e)
                return 0.0

    # Ejecutar en paralelo con semáforo
    results = await asyncio.gather(*(_process_doc(doc) for doc in docs), return_exceptions=True)

    for r in results:
        if isinstance(r, Exception):
            error_count += 1
            logger.error("Hydration task error: %s", r)
        else:
            cost_val = float(r) if r is not None else 0.0  # type: ignore
            if cost_val > 0:
                success_count += 1
            total_cost += cost_val

    elapsed = time.time() - t0

    # ── Resumen ───────────────────────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("HYDRATION COMPLETE")
    logger.info("  Documents processed : %d", len(docs))
    logger.info("  Success             : %d", success_count)
    logger.info("  Errors              : %d", error_count)
    logger.info("  Total time          : %.1fs", elapsed)
    logger.info("  Estimated cost      : $%.4f", total_cost)
    logger.info("  Avg cost/doc        : $%.4f", total_cost / max(success_count, 1))
    logger.info("=" * 50)

    # Decisión GO/OPTIMIZE/STOP basada en costo mensual proyectado
    # Asumiendo ~250 docs/mes
    monthly_projection = total_cost / max(len(docs), 1) * 250
    if monthly_projection < 100:
        logger.info("✅ GO — Proyección mensual: $%.2f (< $100)", monthly_projection)
    elif monthly_projection < 200:
        logger.warning("⚠️  OPTIMIZE — Proyección mensual: $%.2f ($100–$200)", monthly_projection)
    else:
        logger.error("🛑 STOP — Proyección mensual: $%.2f (> $200)", monthly_projection)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fase 2: Hidratación de Graphiti desde Postgres")
    parser.add_argument("--dry-run", action="store_true", help="Preview sin gastar tokens")
    parser.add_argument("--limit", type=int, default=1000, help="Máximo de docs a procesar")
    parser.add_argument(
        "--reset-flags",
        action="store_true",
        help="Re-procesar todos los docs (ignora graph_ingested)",
    )
    args = parser.parse_args()
    asyncio.run(hydrate_graph(dry_run=args.dry_run, limit=args.limit, reset_flags=args.reset_flags))