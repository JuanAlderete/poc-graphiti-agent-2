import tiktoken
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from poc.cost_calculator import calculate_cost
from poc.config import DEFAULT_MODEL

# Configure basic logging if not already configured
logger = logging.getLogger(__name__)

@dataclass
class OperationMetrics:
    operation_type: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    details: List[Dict] = field(default_factory=list)

class TokenTracker:
    # Singleton pattern
    _instance = None
    
    __slots__ = ('_operations', '_encoding')

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TokenTracker, cls).__new__(cls)
            cls._instance._operations = {}
            # Default encoding for most OpenAI models
            try:
                cls._instance._encoding = tiktoken.get_encoding("cl100k_base")
            except Exception as e:
                logger.warning(f"Could not load tiktoken encoding: {e}")
                cls._instance._encoding = None
        return cls._instance

    def start_operation(self, operation_id: str, operation_type: str):
        """Starts tracking a new operation (e.g., 'ingest_doc_1', 'search_query_5')."""
        self._operations[operation_id] = OperationMetrics(operation_type=operation_type)

    def record_usage(self, operation_id: str, tokens_in: int, tokens_out: int, model: str, detail_name: str = "step"):
        """Records token usage for a specific step within an operation."""
        if operation_id not in self._operations:
            logger.warning(f"Attempted to record usage for unknown operation: {operation_id}")
            return
        
        metrics = self._operations[operation_id]
        
        cost = calculate_cost(tokens_in, tokens_out, model)
        
        metrics.tokens_in += tokens_in
        metrics.tokens_out += tokens_out
        metrics.cost_usd += cost
        
        metrics.details.append({
            "step": detail_name,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "model": model,
            "cost": cost
        })

    def estimate_tokens(self, text: str) -> int:
        """Estimates token count for a text string using tiktoken."""
        if not text:
            return 0
        if self._encoding:
            return len(self._encoding.encode(text))
        else:
            # Rough fallback: ~4 chars per token
            return len(text) // 4

    def end_operation(self, operation_id: str) -> Optional[OperationMetrics]:
        """Ends tracking and returns the accumulated metrics."""
        return self._operations.pop(operation_id, None)

    def get_current_metrics(self, operation_id: str) -> Optional[OperationMetrics]:
        """Peeks at current metrics without removing them."""
        return self._operations.get(operation_id)

# Global accessor
tracker = TokenTracker()
