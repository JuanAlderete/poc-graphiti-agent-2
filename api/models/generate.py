"""
api/models/generate.py
----------------------
Modelos Pydantic para el endpoint POST /generate/weekly.
"""
from typing import Optional
from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    dry_run:         bool = Field(default=False,
                                  description="True = simula el run sin llamar al LLM ni publicar en Notion")
    organization_id: str  = Field(default="default",
                                  description="ID del cliente")
    # Opcional: sobrescribir la configuración de Notion Weekly Rules
    # Si se omite, el orquestador lee directamente de Notion
    formats_override: Optional[list[dict]] = Field(
        default=None,
        description="Override de Weekly Rules. Ej: [{formato: reel_cta, topico: objeciones, cantidad: 5}]"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "dry_run": False,
                "organization_id": "marketingmaker"
            }
        }
    }


class GenerateResponse(BaseModel):
    run_id:           str
    organization_id:  str
    pieces_generated: int = 0
    pieces_failed:    int = 0
    pieces_qa_passed: int = 0
    pieces_qa_failed: int = 0
    cost_usd:         float = 0.0
    notion_urls:      list[str] = []
    dry_run:          bool = False
    error:            Optional[str] = None