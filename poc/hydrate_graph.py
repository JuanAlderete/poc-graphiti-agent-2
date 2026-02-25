import asyncio
import logging
from pathlib import Path
from typing import Optional

from agent.graph_utils import GraphClient, DEFAULT_GROUP_ID

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).parent.parent / "documents_to_index"


async def hydrate_graph(
    group_id: Optional[str] = DEFAULT_GROUP_ID,
    delay: float = 0.5,
    reset_flags: bool = False,
):
    """
    Lee todos los archivos .md e incorpora cada uno como episodio en el grafo.

    Args:
        group_id:     Grupo lógico para todos los episodios.
        delay:        Segundos entre episodios para no saturar la API.
        reset_flags:  Si True, limpia Neo4j y resetea los flags de Postgres
                      antes de re-hidratar desde cero. Usar desde el botón
                      "Re-hydrate" del dashboard.
    """
    if reset_flags:
        # Limpiar Neo4j ANTES de re-hidratar para evitar episodios duplicados.
        # Sin este paso los episodios viejos quedan junto a los nuevos.
        logger.info("reset_flags=True: limpiando Neo4j antes de re-hidratar…")
        await GraphClient.clear_graph()

        # Resetear flags en Postgres para que todos los documentos vuelvan a procesarse
        from agent.db_utils import DatabasePool
        pool = await DatabasePool.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE documents SET metadata = metadata - 'graph_ingested', updated_at = NOW()"
            )
            await conn.execute(
                "UPDATE documents SET graphiti_episode_id = NULL, updated_at = NOW()"
            )
        logger.info("Reset graph_ingested y graphiti_episode_id en todos los documentos.")

    if not DOCS_DIR.exists():
        logger.error("Directorio de documentos no encontrado: %s", DOCS_DIR)
        return

    md_files = sorted(DOCS_DIR.glob("*.md"))
    logger.info("Encontrados %d archivos .md para procesar", len(md_files))

    # Construir set de fuentes ya hidratadas (solo cuando reset_flags=False)
    # para saltar documentos que ya están en el grafo sin reprocesarlos.
    already_hydrated: set[str] = set()
    if not reset_flags:
        from agent.db_utils import get_db_connection
        async with get_db_connection() as conn:
            rows = await conn.fetch(
                "SELECT source FROM documents "
                "WHERE (metadata->>'graph_ingested')::boolean IS TRUE"
            )
            for row in rows:
                src = row["source"]
                already_hydrated.add(src)           # "alex.md"
                already_hydrated.add(Path(src).stem)  # "alex" (compatibilidad histórica)
        if already_hydrated:
            logger.info("Se saltearán %d documento(s) ya hidratados.", len(rows))

    processed = 0
    skipped = 0

    for md_file in md_files:
        doc_name = md_file.name  # "alex.md" — consistente con ingest.py

        if doc_name in already_hydrated or md_file.stem in already_hydrated:
            logger.info("Saltando (ya hidratado): %s", doc_name)
            skipped += 1
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
            logger.info("Procesando: %s", doc_name)

            ep_uuid = await GraphClient.add_episode(
                content=content,
                source_reference=doc_name,
                source_description=f"Document from {md_file.name}",
                group_id=group_id,
            )

            # Sincronizar metadata de vuelta a Postgres
            from agent.db_utils import get_db_connection, mark_document_graph_ingested
            async with get_db_connection() as conn:
                doc_record = await conn.fetchrow(
                    # Buscar por nombre con extensión (estándar actual)
                    # El OR con stem cubre documentos ingestados con versiones anteriores
                    "SELECT id FROM documents WHERE source = $1 OR source = $2",
                    doc_name, md_file.stem,
                )
                if doc_record:
                    await mark_document_graph_ingested(str(doc_record["id"]), ep_uuid)
                    logger.info(
                        "Metadata sincronizada en Postgres: %s (ep_uuid=%s)", doc_name, ep_uuid
                    )
                else:
                    logger.warning(
                        "Documento '%s' no encontrado en Postgres. "
                        "Ejecutar ingesta antes de hidratar el grafo.", doc_name
                    )

            logger.info("Episodio agregado: %s (UUID: %s)", doc_name, ep_uuid)
            processed += 1

            if delay > 0:
                await asyncio.sleep(delay)

        except Exception as e:
            logger.error("Error procesando %s: %s", md_file.name, e)
            continue

    logger.info(
        "Hidratación completada: %d procesados, %d saltados (ya hidratados).",
        processed, skipped
    )


async def verify_episodes():
    """Verifica que todos los episodios estén en el grafo."""
    all_episodes = await GraphClient.get_all_episodes(group_ids=None)
    logger.info("Total episodios en grafo: %d", len(all_episodes))
    for ep in all_episodes:
        logger.info("  - %s (group: %s)", ep["name"], ep.get("group_id", "N/A"))
    return all_episodes


async def main():
    await GraphClient.ensure_schema()
    try:
        await hydrate_graph(group_id=DEFAULT_GROUP_ID)
        episodes = await verify_episodes()
        logger.info("Verificación completa: %d episodios en grafo", len(episodes))
    except Exception:
        logger.exception("Hidratación falló")
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())