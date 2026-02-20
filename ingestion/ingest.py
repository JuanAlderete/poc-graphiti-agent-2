import asyncio
import hashlib
import logging
import os
import re
import time
from typing import Any, Optional

from agent.config import settings
from agent.db_utils import DatabasePool, document_exists_by_hash, insert_chunks, insert_document
from agent.graph_utils import GraphClient
from ingestion.chunker import SemanticChunker
from ingestion.embedder import get_embedder
from poc.logging_utils import ingestion_logger
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)

# Patrones de deteccion sin LLM
_TS_PATTERN = re.compile(r"\[(\d{1,2}:\d{2})\]")
_QUOTE_PATTERN = re.compile(r'>\s*"([^"]{20,300})"', re.MULTILINE)
_NAME_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:-\s+)?([A-Z\u00C0-\u00FF][a-z\u00E0-\u00FF]+"
    r"(?:\s+[A-Z\u00C0-\u00FF][a-z\u00E0-\u00FF]+){1,3})"
    r"(?:\s*:|\s+\()",
    re.MULTILINE,
)
_COMPANY_HINT_PATTERN = re.compile(r"\b([A-Z][A-Za-z0-9]{2,}(?:\s[A-Z][A-Za-z0-9]{2,})?)\b")
_PARTICIPANTS_SECTION = re.compile(
    r"Participantes?:(.+?)(?:\n\n|\Z)", re.DOTALL | re.IGNORECASE
)
_COMMON_WORDS = {
    "Este", "Esta", "Pero", "Para", "Como", "Cuando", "Donde",
    "Tiene", "Todo", "Todos", "Tambien", "Ademas", "Sobre", "Entre",
    "Desde", "Hasta", "Estos", "Estas", "Ellos", "Ellas",
}

# Strip de Markdown: reduce tokens que Graphiti procesa en sus ~30 llamadas internas
_MD_STRIP_STEPS = [
    (re.compile(r"\[([^\]]*)\]\([^\)]*\)"), r"\1"),       # links -> solo texto
    (re.compile(r"#{1,6}\s+", re.MULTILINE), ""),          # headers
    (re.compile(r"[*_`]{1,3}"), ""),                       # bold/italic/code
    (re.compile(r"^\s*[-*+]\s+", re.MULTILINE), ""),       # bullet lists
    (re.compile(r"^\s*\d+\.\s+", re.MULTILINE), ""),       # numbered lists
    (re.compile(r"^>\s*", re.MULTILINE), ""),               # blockquotes
    (re.compile(r"\n{3,}"), "\n\n"),                       # blank lines extras
]


def _strip_markdown(text: str) -> str:
    """Elimina sintaxis Markdown preservando contenido textual."""
    result = text
    for pattern, replacement in _MD_STRIP_STEPS:
        result = pattern.sub(replacement, result)
    return result.strip()


class DocumentIngestionPipeline:
    def __init__(self) -> None:
        self.chunker = SemanticChunker()
        self.embedder = get_embedder()

    async def ingest_file(self, file_path: str, skip_graphiti: bool = False) -> Optional[float]:
        """
        Ingesta un archivo. Retorna costo estimado en USD o None si falla.
        No hace re-raise para que gather() continue con los demas archivos.
        """
        start_time = time.time()
        filename = os.path.basename(file_path)
        op_id = f"ingest_{filename}_{int(start_time)}"
        tracker.start_operation(op_id, "ingestion")

        raw_content = ""
        chunks: list[str] = []
        extracted: dict = {}
        cost = 0.0

        try:
            with open(file_path, encoding="utf-8") as fh:
                raw_content = fh.read()

            # 1. Deduplicacion por hash
            content_hash = hashlib.sha256(raw_content.encode()).hexdigest()
            if await document_exists_by_hash(content_hash):
                logger.info("Skipping %s - already ingested.", filename)
                tracker.end_operation(op_id)
                return 0.0

            # 2. Frontmatter YAML
            frontmatter, content_body = self._parse_frontmatter(raw_content)

            # 3. Extraccion heuristica sin LLM
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

            # 4. Chunking
            if extracted["segments"]:
                chunks = self._chunk_by_segments(content_body, extracted["segments"])
            else:
                chunks = self.chunker.chunk(content_body)

            # 5. Embeddings en batch (una sola llamada a la API)
            embeddings, embed_tokens = await self.embedder.generate_embeddings_batch(chunks)
            tracker.record_usage(op_id, embed_tokens, 0, settings.EMBEDDING_MODEL, "embedding_api")

            # 6. Postgres - documento
            doc_id = await insert_document(
                title=frontmatter.get("title", filename),
                source=filename,
                content=content_body,
                metadata=doc_metadata,
            )

            # 7. Postgres - chunks con embeddings
            chunk_metas = [
                {
                    "doc_source": filename,
                    "doc_title": frontmatter.get("title", filename),
                    "category": frontmatter.get("category", ""),
                    "chunk_index": i,
                    "segment_title": self._find_segment_title(
                        chunks[i], extracted["segments"]
                    ),
                }
                for i in range(len(chunks))
            ]
            await insert_chunks(doc_id, chunks, embeddings, chunk_metas=chunk_metas)

            # 8. Graph ingestion
            # Strip MD antes del truncado en graph_utils (maximiza info util en 6000 chars)
            if not skip_graphiti:
                graphiti_content = _strip_markdown(content_body)
                await GraphClient.add_episode(
                    content=graphiti_content,
                    source_reference=filename,
                    source_description=doc_metadata["graphiti_ready_context"],
                )

            latency = time.time() - start_time
            logger.info(
                "Ingested %s: chunks=%d people=%d companies=%d time=%.1fs",
                filename, len(chunks),
                len(extracted["people"]), len(extracted["companies"]),
                latency,
            )

        except Exception:
            # No re-raise: gather() continuara con los archivos restantes
            logger.exception(
                "Failed to ingest %s - skipping, continuing with others.", file_path
            )

        finally:
            metrics = tracker.end_operation(op_id)
            cost = metrics.cost_usd if metrics else 0.0

            ingestion_logger.log_row({
                "episodio_id": op_id,
                "timestamp": start_time,
                "source_type": "markdown",
                "nombre_archivo": filename,
                "longitud_palabras": len(raw_content.split()),
                "chunks_creados": len(chunks),
                "embeddings_tokens": metrics.tokens_in if metrics else 0,
                "entidades_detectadas": (
                    len(extracted.get("people", [])) + len(extracted.get("companies", []))
                ),
                "costo_total_usd": cost,
                "tiempo_seg": time.time() - start_time,
            })

        return cost

    # --- Parsing -----------------------------------------------------------------

    def _parse_frontmatter(self, text: str) -> tuple[dict, str]:
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

    # --- Extraccion heuristica ---------------------------------------------------

    def _extract_entities_heuristic(self, text: str) -> dict:
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

        freq: dict[str, int] = {}
        for m in _COMPANY_HINT_PATTERN.finditer(text):
            w = m.group(1)
            if len(w) > 3 and w not in _COMMON_WORDS:
                freq[w] = freq.get(w, 0) + 1
        companies = sorted(
            [k for k, v in freq.items() if v >= 2], key=lambda x: -freq[x]
        )[:20]

        quotes = _QUOTE_PATTERN.findall(text)[:10]

        segments: list[dict] = []
        for i, line in enumerate(text.splitlines()):
            ts_m = _TS_PATTERN.search(line)
            if ts_m:
                title = line[ts_m.end():].strip(" -\u2013").strip()
                title_clean = re.sub(r"[^\w\s:,.a-zA-Z\u00C0-\u00FF]", "", title).strip()
                segments.append({
                    "timestamp": ts_m.group(1),
                    "title": title_clean[:100],
                    "line_index": i,
                })

        return {"people": people, "companies": companies, "quotes": quotes, "segments": segments}

    def _build_graphiti_context(
        self, filename: str, frontmatter: dict, extracted: dict
    ) -> str:
        parts: list[str] = []
        title = (
            frontmatter.get("title")
            or filename.replace(".md", "").replace("_", " ").title()
        )
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

    # --- Chunking ----------------------------------------------------------------

    def _chunk_by_segments(self, text: str, segments: list[dict]) -> list[str]:
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
                self.chunker.chunk(last)
                if len(last) > self.chunker.chunk_size * 2
                else [last]
            )

        return result if len(result) >= 2 else self.chunker.chunk(text)

    def _find_segment_title(self, chunk_text: str, segments: list[dict]) -> str:
        for seg in segments:
            if seg["title"] and seg["title"][:30] in chunk_text:
                return seg["title"]
        return ""


# --- Entry point -----------------------------------------------------------------

async def ingest_directory(directory: str, skip_graphiti: bool = False) -> None:
    pipeline = DocumentIngestionPipeline()
    await DatabasePool.init_db()

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

    # FIX P1: concurrencia=1 con Graphiti activo.
    # Cada episodio dispara ~30 llamadas LLM internas en paralelo.
    # Con 2 episodios simultaneos = 60 llamadas en paralelo = 429 instantaneo.
    # Con concurrencia=1, los episodios se procesan de a uno:
    #   episodio 1 termina 100% -> episodio 2 empieza
    # Esto elimina el solapamiento sin necesitar delays artificiales.
    # (Con skip_graphiti no hay llamadas LLM: usar concurrencia alta esta bien)
    concurrency = 1 if not skip_graphiti else 8
    sem = asyncio.Semaphore(concurrency)
    t0 = time.time()

    async def _bound(f: str) -> Optional[float]:
        async with sem:
            return await pipeline.ingest_file(f, skip_graphiti=skip_graphiti)

    mode = "Postgres Only" if skip_graphiti else "Postgres + Graphiti (secuencial)"
    logger.info("Ingesting %d files [%s, concurrency=%d]...", len(files), mode, concurrency)

    results = await asyncio.gather(*(_bound(f) for f in files), return_exceptions=True)

    successes = sum(1 for r in results if isinstance(r, float))
    errors = sum(1 for r in results if isinstance(r, Exception))
    total_cost = sum(r for r in results if isinstance(r, float))
    elapsed = time.time() - t0

    logger.info(
        "Done: %d/%d files in %.1fs - total cost $%.4f - errors: %d",
        successes, len(files), elapsed, total_cost, errors,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=str, required=True)
    parser.add_argument("--skip-graphiti", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(ingest_directory(args.dir, skip_graphiti=args.skip_graphiti))