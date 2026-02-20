import re
from typing import List, Optional


class RecursiveChunker:
    """
    Recursive character text splitter.

    Divide texto usando una lista priorizada de separadores
    (parrafo -> linea -> oracion -> palabra -> caracter).
    Si un sub-string sigue superando chunk_size, recursa con el
    siguiente separador.
    """

    def __init__(
        self,
        chunk_size: int = 800,        # OPTIMIZED: 1000 -> 800
        chunk_overlap: int = 100,     # OPTIMIZED: 200 -> 100
        separators: Optional[List[str]] = None,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = min(chunk_overlap, max(0, chunk_size - 1))
        self.separators = separators or ["\n\n", "\n", ". ", " ", ""]

    def chunk(self, text: str) -> List[str]:
        """Divide text en chunks y retorna lista filtrada sin vacios."""
        raw = self._split_text(text, self.separators)
        return [c for c in raw if c.strip()]

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        final_chunks: List[str] = []

        separator = separators[-1]
        next_separators: List[str] = []

        for i, sep in enumerate(separators):
            if sep == "":
                separator = ""
                break
            if re.search(re.escape(sep), text):
                separator = sep
                next_separators = separators[i + 1:]
                break

        splits = text.split(separator) if separator else list(text)

        current_chunk: List[str] = []
        current_len: int = 0

        for split in splits:
            split_len = len(split) + (len(separator) if current_chunk else 0)

            if current_len + split_len > self.chunk_size:
                if current_chunk:
                    chunk_text = separator.join(current_chunk)
                    if chunk_text.strip():
                        final_chunks.append(chunk_text)

                    overlap_chunk: List[str] = []
                    overlap_len = 0
                    for part in reversed(current_chunk):
                        part_len = len(part) + len(separator)
                        if overlap_len + part_len > self.chunk_overlap:
                            break
                        overlap_chunk.insert(0, part)
                        overlap_len += part_len

                    current_chunk = overlap_chunk
                    current_len = overlap_len

                if len(split) > self.chunk_size:
                    if next_separators:
                        sub_chunks = self._split_text(split, next_separators)
                        if sub_chunks and len(sub_chunks[-1]) + current_len <= self.chunk_size:
                            current_chunk.append(sub_chunks[-1])
                            current_len += len(sub_chunks[-1])
                            final_chunks.extend(sub_chunks[:-1])
                        else:
                            final_chunks.extend(sub_chunks)
                    else:
                        final_chunks.append(split[: self.chunk_size])
                else:
                    current_chunk.append(split)
                    current_len += len(split) + len(separator)
            else:
                current_chunk.append(split)
                current_len += split_len

        if current_chunk:
            final_chunks.append(separator.join(current_chunk))

        return final_chunks


class SemanticChunker(RecursiveChunker):
    """Alias backward-compatible de RecursiveChunker."""