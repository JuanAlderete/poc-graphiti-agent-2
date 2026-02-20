import argparse
import asyncio
import logging
import time
from typing import Any

from agent.config import settings
from agent.db_utils import (
    DatabasePool,
    get_all_documents,
    get_documents_missing_from_graph,
    mark_document_graph_ingested,
)
from agent.graph_utils import GraphClient
from poc.cost_calculator import calculate_cost
from poc.token_tracker import tracker

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
        logger.info("--reset-flags activo: procesando TODOS los documentos.")
        docs = await get_all_documents(limit=limit)
    else:
        docs = await get_documents_missing_from_graph(limit=limit)

    if not docs:
        logger.info("✅ No hay documentos pendientes. El grafo está al día.")
        return

    logger.info("Documentos a hidratar: %d", len(docs))

    # ── Dry run ───────────────────────────────────────────────────────────────
    if dry_run:
        logger.info("=== DRY RUN — no se gastarán tokens ===")
        for doc in docs:
            meta = doc.get("metadata", {})
            context = meta.get("graphiti_ready_context", "[sin contexto pre-calculado]")
            people = meta.get("detected_people", [])
            companies = meta.get("detected_companies", [])
            logger.info(
                "  DOC: %s\n    CONTEXT: %s\n    People: %s | Companies: %s",
                doc["source"], context[:120], people[:5], companies[:5],
            )
        logger.info("=== DRY RUN completado (%d docs revisados) ===", len(docs))
        return

    # ── Inicializar Graphiti (build_indices_and_constraints) ──────────────────
    # Esto crea los índices necesarios en Neo4j una sola vez.
    logger.info("Initializing Graphiti and ensuring Neo4j schema…")
    await GraphClient.ensure_schema()

    # ── Hidratación con concurrencia controlada ───────────────────────────────
    concurrency = 3
    sem = asyncio.Semaphore(concurrency)
    total_cost = 0.0
    processed_ids: set[str] = set()  # FIXED: track éxitos por ID, no por costo
    error_count = 0
    t0 = time.time()

    async def _process_doc(doc: dict[str, Any]) -> tuple[str, float]:
        """
        Procesa un único doc.
        Retorna (doc_id, costo_estimado) o lanza excepción.
        """
        source = doc.get("title") or doc.get("source", "unknown")
        doc_id = doc["id"]

        async with sem:
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
                return doc_id, 0.0

            graphiti_context = meta.get("graphiti_ready_context")

            if graphiti_context:
                logger.info("Hydrating: %s | Context: %.80s…", source, graphiti_context)
            else:
                logger.warning(
                    "Hydrating: %s | No pre-calculated context. "
                    "Re-ingestar con el pipeline actualizado mejora la calidad.",
                    source,
                )

            await GraphClient.add_episode(
                content=content,
                source_reference=doc.get("source", source),
                source_description=graphiti_context,
            )

            # Marcar como hidratado para reanudar si se interrumpe
            await mark_document_graph_ingested(doc_id)

            # Estimación de costo para el resumen final
            est_tokens_in = tracker.estimate_tokens(content)
            est_tokens_out = int(est_tokens_in * 0.30)
            cost = calculate_cost(est_tokens_in, est_tokens_out, settings.DEFAULT_MODEL)

            return doc_id, cost

    # Ejecutar en paralelo
    results = await asyncio.gather(
        *(_process_doc(doc) for doc in docs),
        return_exceptions=True,
    )

    for r in results:
        if isinstance(r, Exception):
            error_count += 1
            logger.error("Hydration task error: %s", r)
        else:
            doc_id, cost_val = r  # type: ignore[misc]
            processed_ids.add(doc_id)
            total_cost += cost_val

    elapsed = time.time() - t0
    success_count = len(processed_ids)  # FIXED: count basado en IDs procesados

    # ── Resumen ───────────────────────────────────────────────────────────────
    logger.info("=" * 55)
    logger.info("HYDRATION COMPLETE")
    logger.info("  Documentos procesados : %d", len(docs))
    logger.info("  Exitosos              : %d", success_count)
    logger.info("  Errores               : %d", error_count)
    logger.info("  Tiempo total          : %.1fs", elapsed)
    logger.info("  Costo estimado total  : $%.4f", total_cost)
    logger.info("  Costo promedio/doc    : $%.4f", total_cost / max(success_count, 1))
    logger.info("=" * 55)

    # ── Decisión GO/OPTIMIZE/STOP (proyección a 250 docs/mes) ────────────────
    avg_cost = total_cost / max(success_count, 1)
    monthly_projection = avg_cost * 250
    if monthly_projection < 100:
        logger.info("✅ GO — Proyección mensual (250 docs): $%.2f (< $100)", monthly_projection)
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
        help="Re-procesar todos los docs (ignora el flag graph_ingested)",
    )
    args = parser.parse_args()
    asyncio.run(hydrate_graph(dry_run=args.dry_run, limit=args.limit, reset_flags=args.reset_flags))