import argparse
import asyncio
import json
import logging
import re
import time
from typing import Any, Optional

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

_MD_STRIP_STEPS = [
    (re.compile(r"\[([^\]]*)\]\([^\)]*\)"), r"\1"),
    (re.compile(r"#{1,6}\s+", re.MULTILINE), ""),
    (re.compile(r"[*_`]{1,3}"), ""),
    (re.compile(r"^\s*[-*+]\s+", re.MULTILINE), ""),
    (re.compile(r"^\s*\d+\.\s+", re.MULTILINE), ""),
    (re.compile(r"^>\s*", re.MULTILINE), ""),
    (re.compile(r"\n{3,}"), "\n\n"),
]


def _strip_markdown(text: str) -> str:
    result = text
    for pattern, replacement in _MD_STRIP_STEPS:
        result = pattern.sub(replacement, result)
    return result.strip()


async def _process_one_doc(
    doc: dict[str, Any],
    delay_before: float = 0.0,
) -> tuple[str, float]:
    source = doc.get("title") or doc.get("source", "unknown")
    doc_id = doc["id"]

    meta = doc.get("metadata", {})
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}

    content = doc.get("content", "")
    if not content.strip():
        logger.warning("Skipping %s - empty content.", source)
        return doc_id, 0.0

    graphiti_context = meta.get("graphiti_ready_context")

    if delay_before > 0:
        logger.info("Waiting %.1fs before next episode...", delay_before)
        await asyncio.sleep(delay_before)

    content_clean = _strip_markdown(content)

    await GraphClient.add_episode(
        content=content_clean,
        source_reference=doc.get("source", source),
        source_description=graphiti_context,
    )

    await mark_document_graph_ingested(doc_id)

    est_tokens_in = tracker.estimate_tokens(content_clean)
    est_tokens_out = int(est_tokens_in * 0.30)
    cost = calculate_cost(est_tokens_in, est_tokens_out, settings.DEFAULT_MODEL)
    logger.info("Episode '%s' done - est. cost $%.4f", source, cost)

    return doc_id, cost


async def hydrate_graph(
    dry_run: bool = False,
    limit: int = 1000,
    reset_flags: bool = False,
    delay_between_docs: float = 5.0,
) -> None:
    """
    Lee documentos de Postgres y los ingesta en Graphiti de forma SECUENCIAL.

    Args:
        dry_run:            Preview sin gastar tokens.
        limit:              Maximo de documentos a procesar.
        reset_flags:        Si True, reprocesa todos (ignora graph_ingested).
        delay_between_docs: Segundos entre episodios (default 5s).
    """
    logger.info("=== HYDRATE GRAPH - Fase 2 ===")
    await DatabasePool.init_db()

    if reset_flags:
        logger.info("--reset-flags: procesando TODOS los documentos.")
        docs = await get_all_documents(limit=limit)
    else:
        docs = await get_documents_missing_from_graph(limit=limit)

    if not docs:
        logger.info("[OK] No hay documentos pendientes.")
        return

    logger.info(
        "Documentos a hidratar: %d | Modo: SECUENCIAL | Delay: %.1fs",
        len(docs), delay_between_docs,
    )

    if dry_run:
        logger.info("=== DRY RUN ===")
        for doc in docs:
            meta = doc.get("metadata", {})
            context = meta.get("graphiti_ready_context", "[sin contexto]")
            logger.info("  DOC: %s | CONTEXT: %s", doc["source"], context[:120])
        logger.info("=== DRY RUN completado (%d docs) ===", len(docs))
        return

    logger.info("Initializing Graphiti...")
    await GraphClient.ensure_schema()

    total_cost = 0.0
    processed_ids: set[str] = set()
    error_count = 0
    t0 = time.time()

    for i, doc in enumerate(docs, 1):
        source = doc.get("title") or doc.get("source", "unknown")
        logger.info("--- [%d/%d] %s", i, len(docs), source)

        try:
            doc_id, cost = await _process_one_doc(
                doc,
                delay_before=delay_between_docs if i > 1 else 0.0,
            )
            processed_ids.add(doc_id)
            total_cost += cost
        except Exception as e:
            error_count += 1
            logger.error("Error en '%s': %s", source, e)

    elapsed = time.time() - t0
    success_count = len(processed_ids)

    logger.info("=" * 55)
    logger.info("HYDRATION COMPLETE")
    logger.info("  Documentos procesados : %d", len(docs))
    logger.info("  Exitosos              : %d", success_count)
    logger.info("  Errores               : %d", error_count)
    logger.info("  Tiempo total          : %.1fs (%.1f min)", elapsed, elapsed / 60)
    logger.info("  Costo estimado total  : $%.4f", total_cost)
    logger.info("  Costo promedio/doc    : $%.4f", total_cost / max(success_count, 1))
    logger.info("=" * 55)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fase 2: Hidratacion de Graphiti")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--reset-flags", action="store_true")
    parser.add_argument(
        "--delay", type=float, default=5.0,
        help="Segundos entre episodios (default 5). Usar 0 si el tier lo permite.",
    )
    args = parser.parse_args()
    asyncio.run(
        hydrate_graph(
            dry_run=args.dry_run,
            limit=args.limit,
            reset_flags=args.reset_flags,
            delay_between_docs=args.delay,
        )
    )