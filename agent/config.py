from poc.config import config as _config, AppConfig, get_model_cost, MODEL_PRICING

# `settings` es el alias usado por el código legacy del POC
settings = _config

# Re-exportar todo lo que pueda necesitarse
__all__ = ["settings", "config", "AppConfig", "get_model_cost", "MODEL_PRICING"]