"""
api/models/ingest.py
--------------------
Modelos Pydantic para el endpoint POST /ingest.
"""
from typing import Optional
from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    filename:      str = Field(..., description="Nombre del archivo original")
    content:       str = Field(..., description="Texto completo del documento")
    source_type:   str = Field(default="markdown",
                               description="llamada_venta | sesion_grupal | podcast | masterclass | markdown")
    skip_graphiti: bool = Field(default=True,
                                description="True = solo Postgres. False = también Neo4j (requiere ENABLE_GRAPH=true)")
    organization_id: str = Field(default="default",
                                 description="ID del cliente/organización para multi-tenant")
    extra: dict = Field(default_factory=dict,
                        description="Metadata extra: edition, alumno_id, fecha, etc.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "filename": "sesion_14_validacion.md",
                "content": "# Sesión 14\nEn esta sesión trabajamos la validación de ideas...",
                "source_type": "sesion_grupal",
                "skip_graphiti": True,
                "organization_id": "marketingmaker",
                "extra": {"edition": 14, "alumno_id": "juan-garcia"}
            }
        }
    }


class IngestResponse(BaseModel):
    doc_id:             Optional[str] = None
    chunks_count:       int = 0
    entities_extracted: int = 0
    cost_usd:           float = 0.0
    skipped:            bool = False
    error:              Optional[str] = None
    organization_id:    str = "default"