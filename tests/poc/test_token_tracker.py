import pytest
from poc.token_tracker import tracker
from poc.config import DEFAULT_MODEL

def test_singleton():
    t1 = tracker
    t2 = tracker
    assert t1 is t2

def test_token_estimation():
    text = "Hello world"
    # tiktoken 'cl100k_base' usually encodes "Hello world" as 2 tokens
    assert tracker.estimate_tokens(text) > 0

def test_operation_tracking():
    op_id = "test_op_1"
    tracker.start_operation(op_id, "test_type")
    
    tracker.record_usage(op_id, 100, 50, DEFAULT_MODEL, "step1")
    
    metrics = tracker.get_current_metrics(op_id)
    assert metrics is not None
    assert metrics.tokens_in == 100
    assert metrics.tokens_out == 50
    assert metrics.cost_usd > 0
    
    final_metrics = tracker.end_operation(op_id)
    assert final_metrics.tokens_in == 100
    assert tracker.get_current_metrics(op_id) is None
