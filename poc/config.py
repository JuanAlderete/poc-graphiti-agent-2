import os
from pydantic import Field
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

    # Models
    DEFAULT_MODEL: str = Field(default="gpt-4o-mini")
    EMBEDDING_MODEL: str = Field(default="text-embedding-3-small")

config = AppConfig()

# Dynamic Model Selection based on Provider
if config.LLM_PROVIDER.lower() == "gemini":
    # Override defaults if provider is Gemini and models are still OpenAI defaults
    if config.DEFAULT_MODEL == "gpt-4o-mini":
        config.DEFAULT_MODEL = "gemini-1.5-flash"
    if config.EMBEDDING_MODEL == "text-embedding-3-small":
        config.EMBEDDING_MODEL = "text-embedding-004" # Standard Gemini embedding model name


DEFAULT_MODEL = config.DEFAULT_MODEL
EMBEDDING_MODEL = config.EMBEDDING_MODEL



# Export API keys to environment variables for libraries that rely on them (e.g., Graphiti, OpenAI)
if config.OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = config.OPENAI_API_KEY
if config.GEMINI_API_KEY:
    os.environ["GEMINI_API_KEY"] = config.GEMINI_API_KEY


# Pricing Constants (USD per 1M tokens)
# Source: OpenAI / Google Pricing Pages as of Feb 2026 (Hypothetical/Current)

class ModelPricing:
    def __init__(self, input_price, output_price):
        self.input_price = input_price
        self.output_price = output_price

# Pricing Registry
MODEL_PRICING = {
    # OpenAI
    "gpt-4o-mini": ModelPricing(0.150, 0.600),
    "gpt-4o": ModelPricing(2.50, 10.00),
    "text-embedding-3-small": ModelPricing(0.02, 0.0),
    "text-embedding-3-large": ModelPricing(0.13, 0.0),
    
    # Gemini (Approximation based on Flash/Pro tiers)
    "gemini-1.5-flash": ModelPricing(0.075, 0.30), # Example pricing
    "gemini-1.5-pro": ModelPricing(3.50, 10.50),
    "text-embedding-004": ModelPricing(0.025, 0.0), # Approx Vertex AI pricing
}




