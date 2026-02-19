from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class IngestionConfig(BaseModel):
    chunk_size: int = 1000
    chunk_overlap: int = 200
    embedding_model: str = "text-embedding-3-small"

class SearchResult(BaseModel):
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
    source: str = "unknown"

class AgentQuery(BaseModel):
    query: str
    search_type: str = "hybrid" # vector, graph, hybrid
    filters: Optional[Dict[str, Any]] = None
