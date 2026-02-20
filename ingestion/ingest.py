import asyncio
import hashlib
import logging
import os
import re
import time
from typing import Any

from agent.config import settings
from agent.db_utils import DatabasePool, document_exists_by_hash, insert_chunks, insert_document
from agent.graph_utils import GraphClient
from ingestion.chunker import SemanticChunker
from ingestion.embedder import get_embedder
from poc.logging_utils import ingestion_logger
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)

# ─── Patrones de detección sin LLM ───────────────────────────────────────────

_TS_PATTERN = re.compile(r"\[(\d{1,2}:\d{2})\]")
_QUOTE_PATTERN = re.compile(r'>\s*"([^"]{20,300})"', re.MULTILINE)
_NAME_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:-\s+)?([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3})"
    r"(?:\s*:|\s+\()",
    re.MULTILINE,
)
_COMPANY_HINT_PATTERN = re.compile(r"\b([A-Z][A-Za-z0-9]{2,}(?:\s[A-Z][A-Za-z0-9]{2,})?)\b")
_PARTICIPANTS_SECTION = re.compile(
    r"Participantes?:(.+?)(?:\n\n|\Z)", re.DOTALL | re.IGNORECASE
)

_COMMON_WORDS = {
    "Este", "Esta", "Pero", "Para", "Como", "Cuando", "Donde",
    "Tiene", "Todo", "Todos", "También", "Además", "Sobre", "Entre",
    "Desde", "Hasta", "Estos", "Estas", "Ellos", "Ellas",
}


class DocumentIngestionPipeline:
    def __init__(self) -> None:
        self.chunker = SemanticChunker()
        self.embedder = get_embedder()

    async def ingest_file(self, file_path: str, skip_graphiti: bool = False) -> float:
        """Ingesta un archivo. Retorna el costo estimado en USD."""
        start_time = time.time()
        filename = os.path.basename(file_path)
        op_id = f"ingest_{filename}_{int(start_time)}"
        tracker.start_operation(op_id, "ingestion")
        # FIXED: ya no se llama end_operation en el try block.
        # Solo se llama en finally para garantizar cleanup.

        try:
            with open(file_path, encoding="utf-8") as fh:
                raw_content = fh.read()

            # ── 1. Deduplicación ──────────────────────────────────────────
            content_hash = hashlib.sha256(raw_content.encode()).hexdigest()
            if await document_exists_by_hash(content_hash):
                logger.info("Skipping %s — already ingested (hash match).", filename)
                return 0.0

            # ── 2. Frontmatter ────────────────────────────────────────────
            frontmatter, content_body = self._parse_frontmatter(raw_content)

            # ── 3. Extracción heurística (sin LLM, costo $0) ──────────────
            extracted = self._extract_entities_heuristic(content_body)

            doc_metadata: dict[str, Any] = {
                "source_type": "markdown",
                "filename": filename,
                "content_hash": content_hash,
                **frontmatter,
                "detected_people": extracted["people"],
                "detected_companies": extracted["companies"],
                "detected_quotes_count": len(extracted["quotes"]),
                "detected_segments": extracted["segments"],
                "graphiti_ready_context": self._build_graphiti_context(
                    filename, frontmatter, extracted
                ),
            }

            # ── 4. Chunking respetando segmentos temporales ───────────────
            if extracted["segments"]:
                chunks = self._chunk_by_segments(content_body, extracted["segments"])
            else:
                chunks = self.chunker.chunk(content_body)

            # ── 5. Embedding ──────────────────────────────────────────────
            embeddings, embed_tokens = await self.embedder.generate_embeddings_batch(chunks)
            tracker.record_usage(op_id, embed_tokens, 0, settings.EMBEDDING_MODEL, "embedding_api")

            # ── 6. Postgres — documento ───────────────────────────────────
            doc_id = await insert_document(
                title=frontmatter.get("title", filename),
                source=filename,
                content=content_body,
                metadata=doc_metadata,
            )

            # ── 7. Postgres — chunks con metadata enriquecida ─────────────
            chunk_metas = [
                {
                    "doc_source": filename,
                    "doc_title": frontmatter.get("title", filename),
                    "category": frontmatter.get("category", ""),
                    "chunk_index": i,
                    "segment_title": self._find_segment_title(chunks[i], extracted["segments"]),
                }
                for i in range(len(chunks))
            ]
            await insert_chunks(doc_id, chunks, embeddings, chunk_metas=chunk_metas)

            # ── 8. Graph ingestion (opcional) ─────────────────────────────
            if not skip_graphiti:
                await GraphClient.add_episode(
                    content=content_body,
                    source_reference=filename,
                    source_description=doc_metadata["graphiti_ready_context"],
                )

            latency = time.time() - start_time
            logger.info(
                "Ingested %s: chunks=%d people=%d companies=%d time=%.2fs",
                filename, len(chunks),
                len(extracted["people"]), len(extracted["companies"]),
                latency,
            )
            return 0.0  # cost se calcula abajo en finally

        except Exception:
            logger.exception("Failed to ingest %s", file_path)
            raise
        finally:
            # FIXED: end_operation SOLO aquí, una única vez
            metrics = tracker.end_operation(op_id)
            cost = metrics.cost_usd if metrics else 0.0

            ingestion_logger.log_row({
                "episodio_id": op_id,
                "timestamp": start_time,
                "source_type": "markdown",
                "nombre_archivo": filename,
                "longitud_palabras": len(raw_content.split()) if 'raw_content' in dir() else 0,
                "chunks_creados": len(chunks) if 'chunks' in dir() else 0,
                "embeddings_tokens": metrics.tokens_in if metrics else 0,
                "entidades_detectadas": (
                    len(extracted.get("people", [])) + len(extracted.get("companies", []))
                    if 'extracted' in dir() else 0
                ),
                "costo_total_usd": cost,
                "tiempo_seg": time.time() - start_time,
            })

    # ─── Parsing ──────────────────────────────────────────────────────────────

    def _parse_frontmatter(self, text: str) -> tuple[dict, str]:
        """Extrae YAML frontmatter. Retorna (metadata_dict, content_body)."""
        import yaml
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}, text
        fm_lines, body_lines = [], []
        in_fm = True
        for line in lines[1:]:
            if in_fm and line.strip() == "---":
                in_fm = False
                continue
            (fm_lines if in_fm else body_lines).append(line)
        try:
            meta = yaml.safe_load("\n".join(fm_lines)) or {}
            return (meta if isinstance(meta, dict) else {}), "\n".join(body_lines)
        except Exception as e:
            logger.warning("Failed to parse frontmatter: %s", e)
            return {}, text

    # ─── Extracción heurística (sin LLM) ─────────────────────────────────────

    def _extract_entities_heuristic(self, text: str) -> dict:
        """Detecta entidades sin LLM usando regexes y patrones del formato Novotalks."""
        # Personas
        people: list[str] = []
        pm = _PARTICIPANTS_SECTION.search(text)
        if pm:
            people = [m.group(1).strip() for m in _NAME_PATTERN.finditer(pm.group(1))]
        if not people:
            seen: set[str] = set()
            for m in _NAME_PATTERN.finditer(text):
                n = m.group(1).strip()
                if n not in seen and len(n.split()) >= 2:
                    seen.add(n)
                    people.append(n)
            people = people[:15]

        # Empresas / herramientas
        freq: dict[str, int] = {}
        for m in _COMPANY_HINT_PATTERN.finditer(text):
            w = m.group(1)
            if len(w) > 3 and w not in _COMMON_WORDS:
                freq[w] = freq.get(w, 0) + 1
        companies = sorted([k for k, v in freq.items() if v >= 2], key=lambda x: -freq[x])[:20]

        # Citas
        quotes = _QUOTE_PATTERN.findall(text)[:10]

        # Segmentos con timestamp
        segments: list[dict] = []
        for i, line in enumerate(text.splitlines()):
            ts_m = _TS_PATTERN.search(line)
            if ts_m:
                title = line[ts_m.end():].strip(" -–").strip()
                title_clean = re.sub(r"[^\w\s:áéíóúñÁÉÍÓÚÑ,.]", "", title).strip()
                segments.append({
                    "timestamp": ts_m.group(1),
                    "title": title_clean[:100],
                    "line_index": i,
                })

        return {"people": people, "companies": companies, "quotes": quotes, "segments": segments}

    def _build_graphiti_context(
        self, filename: str, frontmatter: dict, extracted: dict
    ) -> str:
        """Construye el string para source_description en add_episode()."""
        parts: list[str] = []
        title = frontmatter.get("title") or filename.replace(".md", "").replace("_", " ").title()
        parts.append(f"Document: {title}")

        for key in ("category", "date", "episode", "guest", "host"):
            if frontmatter.get(key):
                parts.append(f"{key.capitalize()}: {frontmatter[key]}")

        if extracted["people"]:
            parts.append(f"People: {', '.join(extracted['people'][:8])}")
        if extracted["companies"]:
            parts.append(f"Organizations: {', '.join(extracted['companies'][:10])}")
        if extracted["segments"]:
            titles = [s["title"] for s in extracted["segments"] if s["title"]][:5]
            if titles:
                parts.append(f"Topics: {'; '.join(titles)}")

        return " | ".join(parts)

    # ─── Chunking por segmentos ────────────────────────────────────────────────

    def _chunk_by_segments(self, text: str, segments: list[dict]) -> list[str]:
        """Divide el texto respetando timestamps como límites naturales de chunk."""
        if len(segments) < 2:
            return self.chunker.chunk(text)

        lines = text.splitlines()
        result: list[str] = []
        prev = 0

        for seg in segments:
            idx = seg["line_index"]
            if idx > prev:
                block = "\n".join(lines[prev:idx]).strip()
                if len(block) > 100:
                    if len(block) > self.chunker.chunk_size * 2:
                        result.extend(self.chunker.chunk(block))
                    else:
                        result.append(block)
            prev = idx

        last = "\n".join(lines[prev:]).strip()
        if len(last) > 100:
            result.extend(
                self.chunker.chunk(last) if len(last) > self.chunker.chunk_size * 2 else [last]
            )

        return result if len(result) >= 2 else self.chunker.chunk(text)

    def _find_segment_title(self, chunk_text: str, segments: list[dict]) -> str:
        for seg in segments:
            if seg["title"] and seg["title"][:30] in chunk_text:
                return seg["title"]
        return ""


# ─── Entry point ──────────────────────────────────────────────────────────────

async def ingest_directory(directory: str, skip_graphiti: bool = False) -> None:
    pipeline = DocumentIngestionPipeline()
    await DatabasePool.init_db()

    # Asegurar que Graphiti está inicializado ANTES del bucle de ingesta
    # (build_indices_and_constraints solo se llama una vez gracias al flag _initialized)
    if not skip_graphiti:
        await GraphClient.ensure_schema()

    files = sorted([
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.endswith(".md")
    ])
    if not files:
        logger.warning("No .md files found in '%s'.", directory)
        return

    concurrency = 3 if not skip_graphiti else 5
    sem = asyncio.Semaphore(concurrency)
    t0 = time.time()

    async def _bound(f: str) -> float:
        async with sem:
            return await pipeline.ingest_file(f, skip_graphiti=skip_graphiti) or 0.0

    mode = "Postgres Only" if skip_graphiti else "Postgres + Graphiti"
    logger.info("Ingesting %d files [%s, concurrency=%d]…", len(files), mode, concurrency)

    results = await asyncio.gather(*(_bound(f) for f in files), return_exceptions=True)
    total = sum(r for r in results if isinstance(r, float))
    errors = sum(1 for r in results if isinstance(r, Exception))
    elapsed = time.time() - t0
    logger.info(
        "Done: %d files in %.1fs — total cost $%.4f — errors: %d",
        len(files), elapsed, total, errors,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=str, required=True)
    parser.add_argument("--skip-graphiti", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(ingest_directory(args.dir, skip_graphiti=args.skip_graphiti))