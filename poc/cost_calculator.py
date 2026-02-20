from poc.config import MODEL_PRICING

def calculate_cost(tokens_in: int, tokens_out: int, model_name: str) -> float:
    """
    Returns estimated cost in USD for the given token counts and model.

    Returns 0.0 (with no error) for unknown models so that a missing pricing
    entry never breaks a production run — add a log warning so it is visible.
    """
    pricing = MODEL_PRICING.get(model_name)
    if pricing is None:
        # Import here to avoid circular import at module level
        import logging
        logging.getLogger(__name__).warning(
            "calculate_cost: no pricing entry for model '%s' — cost recorded as $0.00", model_name
        )
        return 0.0

    cost_in = (tokens_in / 1_000_000) * pricing.input_price
    cost_out = (tokens_out / 1_000_000) * pricing.output_price
    return cost_in + cost_out

def format_cost(cost: float) -> str:
    """Human-readable cost string with 6 decimal places for micro-costs."""
    return f"${cost:.6f}"