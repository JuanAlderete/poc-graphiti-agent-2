import os
from dataclasses import dataclass
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # PROVEEDOR LLM
    # Controla qué API se usa para generación Y embeddings.
    # Valores: openai | ollama | gemini
    # -------------------------------------------------------------------------
    LLM_PROVIDER: str = Field(default="openai", description="openai | ollama | gemini")

    # -------------------------------------------------------------------------
    # OPENAI / OLLAMA (compatible con API OpenAI)
    # Ollama expone la misma API en http://localhost:11434/v1
    # El cliente (AsyncOpenAI) solo necesita base_url diferente.
    # -------------------------------------------------------------------------
    OPENAI_API_KEY: str = Field(default="ollama", description="API key. Usar 'ollama' para Ollama local.")
    OPENAI_BASE_URL: Optional[str] = Field(
        default=None,
        description="URL base de la API. None = OpenAI oficial. Para Ollama: http://localhost:11434/v1"
    )

    # -------------------------------------------------------------------------
    # GEMINI
    # -------------------------------------------------------------------------
    GEMINI_API_KEY: str = Field(default="", description="Google Gemini API Key")

    # -------------------------------------------------------------------------
    # MODELOS — se auto-configuran según LLM_PROVIDER si no se especifican
    # Se pueden sobrescribir explícitamente en .env.
    # -------------------------------------------------------------------------
    DEFAULT_MODEL: str = Field(
        default="",
        description="Modelo de generación. Auto: gpt-4.1-mini | llama3.1:8b | gemini-1.5-flash"
    )
    FALLBACK_MODEL: str = Field(
        default="",
        description="Modelo de fallback cuando budget > 90%"
    )
    EMBEDDING_MODEL: str = Field(
        default="",
        description="Modelo de embeddings. Auto: text-embedding-3-small | nomic-embed-text | text-embedding-004"
    )

    # -------------------------------------------------------------------------
    # EMBEDDING DIMS — se auto-calculan según EMBEDDING_MODEL
    # Usado por db_utils.py para crear la columna vector con las dims correctas.
    # ATENCIÓN: Cambiar de proveedor requiere resetear la DB (scripts/reset_db.sh)
    # -------------------------------------------------------------------------
    EMBEDDING_DIMS: int = Field(
        default=0,
        description="Dimensiones del vector. 0 = auto-detectar según proveedor."
    )

    # -------------------------------------------------------------------------
    # POSTGRESQL
    # -------------------------------------------------------------------------
    POSTGRES_USER: str = Field(default="novolabs")
    POSTGRES_PASSWORD: str = Field(default="")
    POSTGRES_DB: str = Field(default="novolabs")
    POSTGRES_HOST: str = Field(default="localhost")
    POSTGRES_PORT: int = Field(default=5432)

    # -------------------------------------------------------------------------
    # NEO4J — OPCIONAL (Fase 2+)
    # -------------------------------------------------------------------------
    ENABLE_GRAPH: bool = Field(default=False, description="Activar Neo4j. False en Fase 1.")
    NEO4J_URI: str = Field(default="bolt://localhost:7687")
    NEO4J_USER: str = Field(default="neo4j")
    NEO4J_PASSWORD: str = Field(default="")

    # -------------------------------------------------------------------------
    # BUDGET GUARD
    # En modo local (Ollama) el costo es $0, el guard se deshabilita automáticamente.
    # -------------------------------------------------------------------------
    MONTHLY_BUDGET_USD: float = Field(
        default=50.0,
        description="Presupuesto mensual en USD. 0 = sin límite. Auto-deshabilitado en Ollama."
    )
    BUDGET_ALERT_THRESHOLD_1: float = Field(default=0.70, description="70% → alerta Telegram")
    BUDGET_ALERT_THRESHOLD_2: float = Field(default=0.90, description="90% → cambio a FALLBACK_MODEL")
    BUDGET_TRACKING_FILE: str = Field(default="logs/monthly_budget.json")

    # -------------------------------------------------------------------------
    # NOTION
    # -------------------------------------------------------------------------
    NOTION_TOKEN: str = Field(default="")
    NOTION_REELS_DB: str = Field(default="")
    NOTION_EMAIL_DB: str = Field(default="")
    NOTION_HISTORIA_DB: str = Field(default="")
    NOTION_ADS_DB: str = Field(default="")
    NOTION_RUNS_DB: str = Field(default="")
    NOTION_RULES_DB: str = Field(default="")

    # -------------------------------------------------------------------------
    # TELEGRAM
    # -------------------------------------------------------------------------
    TELEGRAM_BOT_TOKEN: str = Field(default="")
    TELEGRAM_CHAT_ID: str = Field(default="")

    # -------------------------------------------------------------------------
    # APP
    # -------------------------------------------------------------------------
    LOG_LEVEL: str = Field(default="INFO")
    ENVIRONMENT: str = Field(default="development")
    API_PORT: int = Field(default=8000)
    MAX_CONCURRENT_GENERATIONS: int = Field(default=5)

    # =========================================================================
    # VALIDADOR: auto-configura modelos y URLs según LLM_PROVIDER
    # =========================================================================
    @model_validator(mode="after")
    def _resolve_provider_defaults(self) -> "AppConfig":
        provider = self.LLM_PROVIDER.lower()

        if provider == "openai":
            if not self.DEFAULT_MODEL:
                object.__setattr__(self, "DEFAULT_MODEL", "gpt-4.1-mini")
            if not self.FALLBACK_MODEL:
                object.__setattr__(self, "FALLBACK_MODEL", "gpt-4.1-mini")
            if not self.EMBEDDING_MODEL:
                object.__setattr__(self, "EMBEDDING_MODEL", "text-embedding-3-small")
            if not self.EMBEDDING_DIMS:
                object.__setattr__(self, "EMBEDDING_DIMS", 1536)
            # OPENAI_BASE_URL ya es None por defecto → usa api.openai.com

        elif provider == "ollama":
            if not self.DEFAULT_MODEL:
                object.__setattr__(self, "DEFAULT_MODEL", "llama3.1:8b")
            if not self.FALLBACK_MODEL:
                object.__setattr__(self, "FALLBACK_MODEL", "llama3.1:8b")
            if not self.EMBEDDING_MODEL:
                object.__setattr__(self, "EMBEDDING_MODEL", "nomic-embed-text")
            if not self.EMBEDDING_DIMS:
                object.__setattr__(self, "EMBEDDING_DIMS", 768)
            if not self.OPENAI_BASE_URL:
                object.__setattr__(self, "OPENAI_BASE_URL", "http://localhost:11434/v1")
            # En local: budget infinito (costo $0)
            if self.OPENAI_API_KEY in ("", "ollama", "sk-..."):
                object.__setattr__(self, "OPENAI_API_KEY", "ollama")

        elif provider == "gemini":
            if not self.DEFAULT_MODEL:
                object.__setattr__(self, "DEFAULT_MODEL", "gemini-1.5-flash")
            if not self.FALLBACK_MODEL:
                object.__setattr__(self, "FALLBACK_MODEL", "gemini-1.5-flash")
            if not self.EMBEDDING_MODEL:
                object.__setattr__(self, "EMBEDDING_MODEL", "text-embedding-004")
            if not self.EMBEDDING_DIMS:
                object.__setattr__(self, "EMBEDDING_DIMS", 768)

        else:
            raise ValueError(
                f"LLM_PROVIDER='{provider}' no reconocido. "
                "Valores válidos: openai | ollama | gemini"
            )

        return self

    # =========================================================================
    # PROPIEDADES DE CONVENIENCIA
    # =========================================================================

    @property
    def is_local(self) -> bool:
        """True cuando se usa Ollama. Deshabilita budget guard y simplifica logs."""
        return self.LLM_PROVIDER.lower() == "ollama"

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def effective_monthly_budget(self) -> float:
        """Budget efectivo: $0 en Ollama (costo real es $0), el configurado en otros."""
        if self.is_local:
            return 0.0  # Sin límite en local
        return self.MONTHLY_BUDGET_USD


# =============================================================================
# INSTANCIA GLOBAL
# =============================================================================
config = AppConfig()

# Exportar al entorno para que librerías como openai SDK y graphiti los lean
if config.OPENAI_API_KEY:
    os.environ.setdefault("OPENAI_API_KEY", config.OPENAI_API_KEY)
if config.OPENAI_BASE_URL:
    os.environ.setdefault("OPENAI_BASE_URL", config.OPENAI_BASE_URL)
if config.GEMINI_API_KEY:
    os.environ.setdefault("GEMINI_API_KEY", config.GEMINI_API_KEY)

# Shortcuts de módulo (backwards compat con código que importa directamente)
DEFAULT_MODEL: str = config.DEFAULT_MODEL
EMBEDDING_MODEL: str = config.EMBEDDING_MODEL
EMBEDDING_DIMS: int = config.EMBEDDING_DIMS


# =============================================================================
# PRICING REGISTRY (solo relevante para openai/gemini)
# En Ollama todos los costos son 0.
# =============================================================================

@dataclass(frozen=True)
class ModelPricing:
    """Costo en USD por 1 millón de tokens."""
    input_price: float
    output_price: float

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_price + output_tokens * self.output_price) / 1_000_000


# Precios actualizados — revisar en https://openai.com/pricing
MODEL_PRICING: dict[str, ModelPricing] = {
    # OpenAI
    "gpt-4.1-mini":              ModelPricing(0.40,  1.60),
    "gpt-4.1":                   ModelPricing(2.00,  8.00),
    "gpt-4o-mini":               ModelPricing(0.15,  0.60),
    "gpt-4o":                    ModelPricing(5.00, 20.00),
    "gpt-5-mini":                ModelPricing(0.08,  0.32),
    "text-embedding-3-small":    ModelPricing(0.02,  0.00),
    "text-embedding-3-large":    ModelPricing(0.13,  0.00),
    # Gemini
    "gemini-1.5-flash":          ModelPricing(0.075, 0.30),
    "gemini-1.5-pro":            ModelPricing(3.50, 10.50),
    "text-embedding-004":        ModelPricing(0.00,  0.00),  # Gratis en Gemini
    # Ollama — siempre $0
    "llama3.1:8b":               ModelPricing(0.00,  0.00),
    "llama3.2":                  ModelPricing(0.00,  0.00),
    "llama3.2:3b":               ModelPricing(0.00,  0.00),
    "mistral":                   ModelPricing(0.00,  0.00),
    "nomic-embed-text":          ModelPricing(0.00,  0.00),
    "mxbai-embed-large":         ModelPricing(0.00,  0.00),
}


def get_model_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calcula el costo de una operación. Retorna 0.0 para modelos locales."""
    if config.is_local:
        return 0.0
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        # Modelo desconocido: estimar con precio de gpt-4.1-mini
        pricing = ModelPricing(0.40, 1.60)
    return pricing.calculate_cost(input_tokens, output_tokens)