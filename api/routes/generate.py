"""
api/routes/generate.py
----------------------
POST /generate/weekly — Dispara la generación semanal completa.

Llamado por n8n cada domingo a las 23:00.
También puede llamarse manualmente para testing.
"""
import logging
import uuid
from fastapi import APIRouter, HTTPException

from api.models.generate import GenerateRequest, GenerateResponse
from poc.budget_guard import check_budget_and_warn
from agent.db_utils import DatabasePool
from orchestrator.main import MainOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/generate/weekly", response_model=GenerateResponse, tags=["Generación"])
async def generate_weekly(request: GenerateRequest) -> GenerateResponse:
    """
    Dispara la generación semanal de contenido utilizando el orquestador principal.

    Lee las reglas de Notion (o usa defaults), busca chunks relevantes
    y genera piezas para cada formato configurado.
    En modo `dry_run=true`, simula el proceso sin llamar a publicación.
    """
    run_id = str(uuid.uuid4())

    logger.info(
        "POST /generate/weekly: run_id=%s org='%s' dry_run=%s",
        run_id, request.organization_id, request.dry_run
    )

    # ── Verificar presupuesto antes de empezar ────────────────────────────────
    if not request.dry_run:
        budget_status = check_budget_and_warn()
        if budget_status == "critical":
            raise HTTPException(
                status_code=402,
                detail="Budget mensual agotado. Aumentar MONTHLY_BUDGET_USD en configuración."
            )

    try:
        await DatabasePool.init_db()

        orchestrator = MainOrchestrator(
            run_id=run_id,
            org_id=request.organization_id,
            dry_run=request.dry_run,
        )

        result = await orchestrator.run(
            formats_override=request.formats_override
        )

        # Mapeo de respuesta Orchestrator -> Pydantic Response del Endpoint
        return GenerateResponse(
            run_id=result.get("run_id", run_id),
            organization_id=request.organization_id,
            pieces_generated=result.get("summary", {}).get("total", 0),
            pieces_failed=result.get("summary", {}).get("failed", 0),
            pieces_qa_passed=result.get("summary", {}).get("passed", 0),
            pieces_qa_failed=0,
            cost_usd=round(result.get("summary", {}).get("cost_usd", 0.0), 4),
            notion_urls=[],
            dry_run=request.dry_run,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error en POST /generate/weekly run_id=%s", run_id)
        raise HTTPException(status_code=500, detail=f"Error en generación: {str(e)}")