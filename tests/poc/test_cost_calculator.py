import pytest
from poc.cost_calculator import calculate_cost
from poc.config import MODEL_PRICING

def test_calculate_cost_known_model():
    model = "gpt-4o-mini"
    pricing = MODEL_PRICING[model]
    
    # 1M tokens in -> should be input_price
    cost = calculate_cost(1_000_000, 0, model)
    assert cost == pricing.input_price
    
    # 1M tokens out -> should be output_price
    cost = calculate_cost(0, 1_000_000, model)
    assert cost == pricing.output_price

def test_calculate_cost_unknown_model():
    cost = calculate_cost(100, 100, "unknown-model-xyz")
    assert cost == 0.0
