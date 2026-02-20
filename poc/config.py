import os
from dataclasses import dataclass
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # LLM Settings
    LLM_PROVIDER: str = Field(default="openai", description="Provider: 'openai' or 'gemini'")
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API Key")
    GEMINI_API_KEY: str = Field(default="", description="Gemini API Key")

    # Neo4j Settings
    NEO4J_URI: str = Field(default="bolt://localhost:7687")
    NEO4J_USER: str = Field(default="neo4j")
    NEO4J_PASSWORD: str = Field(default="password")

    # Postgres Settings
    POSTGRES_USER: str = Field(default="postgres")
    POSTGRES_PASSWORD: str = Field(default="password")
    POSTGRES_DB: str = Field(default="graphiti_poc")
    POSTGRES_HOST: str = Field(default="localhost")
    POSTGRES_PORT: int = Field(default=5432)

    # Models — defaults are for OpenAI; Gemini overrides handled via validator
    DEFAULT_MODEL: str = Field(default="gpt-5-mini")
    EMBEDDING_MODEL: str = Field(default="text-embedding-3-small")

    @model_validator(mode="after")
    def _resolve_gemini_defaults(self) -> "AppConfig":
        """
        FIXED: Previously mutated the object after construction (anti-pattern / Pydantic v2 issue).
        Now handled cleanly via model_validator so the object is fully consistent on creation.
        """
        if self.LLM_PROVIDER.lower() == "gemini":
            if self.DEFAULT_MODEL == "gpt-5-mini":
                object.__setattr__(self, "DEFAULT_MODEL", "gemini-1.5-flash")
            if self.EMBEDDING_MODEL == "text-embedding-3-small":
                object.__setattr__(self, "EMBEDDING_MODEL", "text-embedding-004")
        return self


config = AppConfig()

# Export API keys to env so libraries (graphiti_core, openai SDK) pick them up automatically
if config.OPENAI_API_KEY:
    os.environ.setdefault("OPENAI_API_KEY", config.OPENAI_API_KEY)
if config.GEMINI_API_KEY:
    os.environ.setdefault("GEMINI_API_KEY", config.GEMINI_API_KEY)

# Module-level shortcuts kept for backwards compat
DEFAULT_MODEL: str = config.DEFAULT_MODEL
EMBEDDING_MODEL: str = config.EMBEDDING_MODEL


# ---------------------------------------------------------------------------
# Pricing Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelPricing:
    """USD cost per 1 million tokens."""
    input_price: float
    output_price: float


# Source: OpenAI / Google pricing pages — update as needed
MODEL_PRICING: dict[str, ModelPricing] = {
    # OpenAI
    "gpt-5-mini":               ModelPricing(0.080, 0.320),
    "gpt-4o-mini":              ModelPricing(0.150, 0.600),
    "gpt-4o":                   ModelPricing(2.50,  10.00),
    "text-embedding-3-small":   ModelPricing(0.020, 0.0),
    "text-embedding-3-large":   ModelPricing(0.130, 0.0),
    # Gemini
    "gemini-1.5-flash":         ModelPricing(0.075, 0.30),
    "gemini-1.5-pro":           ModelPricing(3.50,  10.50),
    "text-embedding-004":       ModelPricing(0.025, 0.0),
}