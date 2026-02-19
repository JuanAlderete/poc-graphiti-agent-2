from typing import List
import re

import re
from typing import List, Optional

class RecursiveChunker:
    """
    Implements Recursive Character Chunking (Level 2 Strategy).
    Splits text hierarchically using a list of separators to preserve semantic structure.
    """
    def __init__(
        self, 
        chunk_size: int = 1000, 
        chunk_overlap: int = 200,
        separators: Optional[List[str]] = None
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", ". ", " ", ""]

    def chunk(self, text: str) -> List[str]:
        return self._split_text(text, self.separators)

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        final_chunks = []
        separator = separators[-1]
        new_separators = []
        
        # Find the best separator that works
        for i, sep in enumerate(separators):
            if sep == "":
                separator = ""
                break
            if re.search(re.escape(sep), text):
                separator = sep
                new_separators = separators[i + 1:]
                break
                
        # Split
        if separator:
            splits = text.split(separator)
        else:
            splits = list(text) # Char split if no separator found (shouldn't happen with "")

        # Merge
        current_chunk = []
        current_len = 0
        
        for split in splits:
            # Add separator back if it's not empty/whitespace logic (simplified here)
            # For exact reconstruction we'd need more complex logic, but for RAG 
            # effectively appending the separator to the previous chunk or this one is good.
            # Here we basically lose the specific separator instance unless we capture it.
            # To be simple: we assume the split content is what matters.
            
            split_len = len(split) + len(separator) 
            
            if current_len + split_len > self.chunk_size:
                if current_chunk:
                    # Current chunk full, save it
                    text_chunk = separator.join(current_chunk)
                    if text_chunk.strip():
                        final_chunks.append(text_chunk)
                    
                    # Start new chunk with overlap? 
                    # Recursive overlap is tricky. 
                    # We'll just start fresh or keep last item if small? 
                    # Simple sliding:
                    current_chunk = [split]
                    current_len = split_len
                else:
                    # Single split is too big, recurse
                    if new_separators:
                        sub_chunks = self._split_text(split, new_separators)
                        final_chunks.extend(sub_chunks)
                    else:
                        # desperate hard limit
                        final_chunks.append(split[:self.chunk_size])
            else:
                current_chunk.append(split)
                current_len += split_len
                
        if current_chunk:
             final_chunks.append(separator.join(current_chunk))
             
        return final_chunks

# Alias for compatibility if needed, or we update ingest.py
class SemanticChunker(RecursiveChunker):
    """
    Deprecated name, aliased to RecursiveChunker for backward compatibility.
    """
    pass

