import re
from typing import List, Optional


class RecursiveChunker:
    """
    Splits text recursively using a prioritized list of separators.
    """

    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        separators: Optional[List[str]] = None,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = min(chunk_overlap, max(0, chunk_size - 1))
        self.separators = separators or ["\n\n", "\n", ". ", " ", ""]

    def chunk(self, text: str) -> List[str]:
        raw = self._split_text(text, self.separators)
        return [c for c in raw if c.strip()]

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        final_chunks: List[str] = []

        separator = separators[-1]
        next_seps: List[str] = []
        for i, sep in enumerate(separators):
            if sep == "":
                separator = ""
                break
            if re.search(re.escape(sep), text):
                separator = sep
                next_seps = separators[i + 1:]
                break

        splits = text.split(separator) if separator else list(text)

        current: List[str] = []
        current_len = 0

        for split in splits:
            split_len = len(split) + (len(separator) if current else 0)

            if current_len + split_len > self.chunk_size:
                if current:
                    final_chunks.append(separator.join(current))

                    # Overlap: mantener los últimos N chars como contexto
                    overlap: List[str] = []
                    overlap_len = 0
                    for part in reversed(current):
                        part_len = len(part) + len(separator)
                        if overlap_len + part_len > self.chunk_overlap:
                            break
                        overlap.insert(0, part)
                        overlap_len += part_len
                    current = overlap
                    current_len = overlap_len

                if len(split) > self.chunk_size:
                    if next_seps:
                        sub = self._split_text(split, next_seps)
                        final_chunks.extend(sub)
                    else:
                        final_chunks.append(split[: self.chunk_size])
                else:
                    current.append(split)
                    current_len += split_len
            else:
                current.append(split)
                current_len += split_len

        if current:
            final_chunks.append(separator.join(current))

        return final_chunks


# Alias para compatibilidad con ingest.py original
class SemanticChunker(RecursiveChunker):
    pass