"""
agent/config.py
---------------
Configuración central del proyecto Novolabs AI Engine.

Cambios v2.0:
- ENABLE_GRAPH: controla si Neo4j está activo (default: False en Fase 1)
- MONTHLY_BUDGET_USD + alertas ya estaban en budget_guard, aquí centralizamos
- Eliminadas referencias a Pydantic AI y LangGraph (no se usan en Fase 1)
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Settings:
    # -------------------------------------------------------------------------
    # OPENAI
    # -------------------------------------------------------------------------
    openai_api_key:     str = field(default_factory=lambda: os.environ["OPENAI_API_KEY"])
    default_model:      str = field(default_factory=lambda: os.getenv("DEFAULT_MODEL", "gpt-4.1-mini"))
    fallback_model:     str = field(default_factory=lambda: os.getenv("FALLBACK_MODEL", "gpt-4.1-mini"))
    embedding_model:    str = "text-embedding-3-small"

    # -------------------------------------------------------------------------
    # POSTGRES
    # -------------------------------------------------------------------------
    postgres_host:      str = field(default_factory=lambda: os.getenv("POSTGRES_HOST", "localhost"))
    postgres_port:      int = field(default_factory=lambda: int(os.getenv("POSTGRES_PORT", "5432")))
    postgres_db:        str = field(default_factory=lambda: os.getenv("POSTGRES_DB", "novolabs"))
    postgres_user:      str = field(default_factory=lambda: os.getenv("POSTGRES_USER", "novolabs"))
    postgres_password:  str = field(default_factory=lambda: os.environ.get("POSTGRES_PASSWORD", ""))

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # -------------------------------------------------------------------------
    # NEO4J - OPCIONAL (Fase 2+)
    # En Fase 1: ENABLE_GRAPH=false. El sistema corre 100% con Postgres.
    # En Fase 2+: setear ENABLE_GRAPH=true y levantar con --profile graph
    # -------------------------------------------------------------------------
    enable_graph:       bool = field(default_factory=lambda: os.getenv("ENABLE_GRAPH", "false").lower() == "true")
    neo4j_uri:          str = field(default_factory=lambda: os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    neo4j_user:         str = field(default_factory=lambda: os.getenv("NEO4J_USER", "neo4j"))
    neo4j_password:     str = field(default_factory=lambda: os.getenv("NEO4J_PASSWORD", ""))

    # -------------------------------------------------------------------------
    # BUDGET GUARD
    # -------------------------------------------------------------------------
    monthly_budget_usd:       float = field(default_factory=lambda: float(os.getenv("MONTHLY_BUDGET_USD", "50")))
    budget_alert_threshold_1: float = field(default_factory=lambda: float(os.getenv("BUDGET_ALERT_THRESHOLD_1", "0.70")))
    budget_alert_threshold_2: float = field(default_factory=lambda: float(os.getenv("BUDGET_ALERT_THRESHOLD_2", "0.90")))

    # -------------------------------------------------------------------------
    # NOTION
    # -------------------------------------------------------------------------
    notion_token:       str = field(default_factory=lambda: os.getenv("NOTION_TOKEN", ""))
    notion_reels_db:    str = field(default_factory=lambda: os.getenv("NOTION_REELS_DB", ""))
    notion_email_db:    str = field(default_factory=lambda: os.getenv("NOTION_EMAIL_DB", ""))
    notion_historia_db: str = field(default_factory=lambda: os.getenv("NOTION_HISTORIA_DB", ""))
    notion_ads_db:      str = field(default_factory=lambda: os.getenv("NOTION_ADS_DB", ""))
    notion_runs_db:     str = field(default_factory=lambda: os.getenv("NOTION_RUNS_DB", ""))
    notion_rules_db:    str = field(default_factory=lambda: os.getenv("NOTION_RULES_DB", ""))

    # -------------------------------------------------------------------------
    # TELEGRAM
    # -------------------------------------------------------------------------
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id:   str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

    # -------------------------------------------------------------------------
    # GENERACIÓN
    # -------------------------------------------------------------------------
    max_concurrent_generations: int = 5         # Semáforo de concurrencia (evita 429)
    diversity_lookback_days:    int = 30        # Días para penalizar chunks usados
    diversity_penalty:          float = 0.30   # 30% de penalización en score
    min_relevance_score:        float = 0.40   # Score mínimo antes de aplicar diversidad
    qa_llm_sample_rate:         float = 0.10   # 10% de piezas pasan por QA con LLM

    # -------------------------------------------------------------------------
    # APP
    # -------------------------------------------------------------------------
    log_level:          str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    environment:        str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


# Singleton de settings
settings = Settings()