import re
from typing import List, Optional

class RecursiveChunker:
    """
    Recursive character text splitter.

    Splits text using a prioritised list of separators (paragraph → line →
    sentence → word → char).  When a sub-string still exceeds `chunk_size`,
    the algorithm recurses with the next separator in the list.
    """
    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separators: Optional[List[str]] = None,
    ) -> None:
        self.chunk_size = chunk_size
        # Clamp overlap so it can never equal or exceed chunk_size
        self.chunk_overlap = min(chunk_overlap, max(0, chunk_size - 1))
        self.separators = separators or ["\n\n", "\n", ". ", " ", ""]

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def chunk(self, text: str) -> List[str]:
        """Split *text* into chunks and return a filtered list of non-empty strings."""
        raw = self._split_text(text, self.separators)
        return [c for c in raw if c.strip()]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        final_chunks: List[str] = []

        # Find the best separator for this text
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

        # Split on the chosen separator
        splits = text.split(separator) if separator else list(text)

        current_chunk: List[str] = []
        current_len: int = 0

        for split in splits:
            # Length of this piece including the separator we'll re-join with
            split_len = len(split) + (len(separator) if current_chunk else 0)

            if current_len + split_len > self.chunk_size:
                if current_chunk:
                    # Save current chunk
                    chunk_text = separator.join(current_chunk)
                    if chunk_text.strip():
                        final_chunks.append(chunk_text)

                    # FIXED: carry overlap from tail of current chunk
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

                # If the single split is still larger than chunk_size, recurse
                if len(split) > self.chunk_size:
                    if next_separators:
                        sub_chunks = self._split_text(split, next_separators)
                        # The last sub-chunk may be small enough to merge into the next chunk
                        if sub_chunks and len(sub_chunks[-1]) + current_len <= self.chunk_size:
                            current_chunk.append(sub_chunks[-1])
                            current_len += len(sub_chunks[-1])
                            final_chunks.extend(sub_chunks[:-1])
                        else:
                            final_chunks.extend(sub_chunks)
                    else:
                        # Hard limit: truncate
                        final_chunks.append(split[: self.chunk_size])
                else:
                    current_chunk.append(split)
                    current_len += len(split) + len(separator)
            else:
                current_chunk.append(split)
                current_len += split_len

        # Remaining content
        if current_chunk:
            final_chunks.append(separator.join(current_chunk))

        return final_chunks


# Alias kept for backward compatibility
class SemanticChunker(RecursiveChunker):
    """Backwards-compatible alias for RecursiveChunker."""