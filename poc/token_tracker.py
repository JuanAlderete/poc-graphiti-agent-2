import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import tiktoken

from poc.cost_calculator import calculate_cost
from poc.config import DEFAULT_MODEL

logger = logging.getLogger(__name__)

@dataclass
class OperationMetrics:
    operation_type: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    details: List[Dict] = field(default_factory=list)

class TokenTracker:
    """
    Singleton token tracker.  All public methods are protected by a threading
    Lock so they are safe when called from concurrent asyncio tasks running in
    the same thread (via asyncio.gather) *and* from auxiliary threads.
    """

    _instance: Optional["TokenTracker"] = None
    _class_lock = threading.Lock()

    # Slots only on the instance, not the class — compatible with __new__ trick
    __slots__ = ("_operations", "_encoding", "_lock")

    def __new__(cls) -> "TokenTracker":
        with cls._class_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._operations: Dict[str, OperationMetrics] = {}
                inst._lock = threading.Lock()
                try:
                    inst._encoding = tiktoken.get_encoding("cl100k_base")
                except Exception as exc:
                    logger.warning("tiktoken encoding unavailable: %s", exc)
                    inst._encoding = None
                cls._instance = inst
        return cls._instance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_operation(self, operation_id: str, operation_type: str) -> None:
        """Begin tracking a named operation."""
        with self._lock:
            self._operations[operation_id] = OperationMetrics(operation_type=operation_type)

    def record_usage(
        self,
        operation_id: str,
        tokens_in: int,
        tokens_out: int,
        model: str,
        detail_name: str = "step",
    ) -> None:
        """Accumulate token counts and cost for a sub-step."""
        with self._lock:
            metrics = self._operations.get(operation_id)
            if metrics is None:
                logger.warning("record_usage: unknown operation_id '%s'", operation_id)
                return

            cost = calculate_cost(tokens_in, tokens_out, model)
            metrics.tokens_in += tokens_in
            metrics.tokens_out += tokens_out
            metrics.cost_usd += cost
            metrics.details.append(
                {
                    "step": detail_name,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "model": model,
                    "cost": cost,
                }
            )

    def estimate_tokens(self, text: Optional[str]) -> int:
        """Estimate token count for *text*. Falls back to char/4 heuristic."""
        if not text:
            return 0
        if self._encoding is not None:
            return len(self._encoding.encode(text))
        return max(1, len(text) // 4)

    def end_operation(self, operation_id: str) -> Optional[OperationMetrics]:
        """Finalise and return accumulated metrics, removing the operation."""
        with self._lock:
            return self._operations.pop(operation_id, None)

    def get_current_metrics(self, operation_id: str) -> Optional[OperationMetrics]:
        """Peek at current metrics without removing them."""
        with self._lock:
            return self._operations.get(operation_id)


# Global singleton accessor — import this everywhere
tracker = TokenTracker()