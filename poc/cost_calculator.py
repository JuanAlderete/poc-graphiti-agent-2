from poc.config import MODEL_PRICING

def calculate_cost(tokens_in: int, tokens_out: int, model_name: str) -> float:
    """
    Calculates the estimated cost in USD for a given operation.
    
    Args:
        tokens_in: Number of input/prompt tokens.
        tokens_out: Number of output/completion tokens.
        model_name: Name of the model used (e.g., 'gpt-4o-mini').
        
    Returns:
        float: Estimated cost in USD.
    """
    if model_name not in MODEL_PRICING:
        # Fallback or warning could be logged here. 
        # For now, return 0.0 if unknown to avoid breaking execution, 
        # but ideally should map to a default or closest match.
        return 0.0
    
    pricing = MODEL_PRICING[model_name]
    
    cost_in = (tokens_in / 1_000_000) * pricing.input_price
    cost_out = (tokens_out / 1_000_000) * pricing.output_price
    
    return cost_in + cost_out

def format_cost(cost: float) -> str:
    """Formats cost to 6 decimal places for micro-costs."""
    return f"${cost:.6f}"
