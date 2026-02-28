import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from poc.config import config, get_model_cost

logger = logging.getLogger(__name__)
_lock = threading.Lock()


# =============================================================================
# HELPERS DE ARCHIVO JSON
# =============================================================================

def _get_current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def _load_tracking() -> dict:
    path = Path(config.BUDGET_TRACKING_FILE)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning("No se pudo leer el archivo de budget tracking, empezando desde cero.")
        return {}


def _save_tracking(data: dict) -> None:
    path = Path(config.BUDGET_TRACKING_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# =============================================================================
# API PÚBLICA
# =============================================================================

def get_monthly_spent() -> float:
    """Retorna el gasto total del mes actual en USD. Retorna 0 en modo local."""
    if config.is_local:
        return 0.0
    with _lock:
        data = _load_tracking()
        month = _get_current_month()
        return float(data.get(month, {}).get("spent_usd", 0.0))


def record_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Registra el costo de una operación LLM.

    En modo local (Ollama): no registra nada, retorna 0.0.
    En OpenAI/Gemini: calcula costo, persiste, verifica alertas.

    Returns:
        Costo de la operación en USD.
    """
    cost = get_model_cost(model, input_tokens, output_tokens)

    if config.is_local:
        return 0.0  # Sin tracking en local

    if config.MONTHLY_BUDGET_USD <= 0:
        return cost  # Budget control deshabilitado

    with _lock:
        data = _load_tracking()
        month = _get_current_month()

        if month not in data:
            data[month] = {"spent_usd": 0.0, "operations": 0}

        data[month]["spent_usd"] = round(data[month]["spent_usd"] + cost, 6)
        data[month]["operations"] = data[month].get("operations", 0) + 1
        data[month]["last_updated"] = datetime.now().isoformat()

        _save_tracking(data)

    # Check fuera del lock
    check_budget_and_warn()
    return cost


def check_budget_and_warn() -> str:
    """
    Verifica el estado del presupuesto y emite alertas.

    Returns:
        'disabled' → Ollama local o budget=0
        'ok'       → < 70% usado
        'warning'  → 70-90% usado
        'critical' → > 90% usado (activa fallback model)
    """
    if config.is_local:
        return "disabled"

    budget = config.MONTHLY_BUDGET_USD
    if budget <= 0:
        return "disabled"

    spent = get_monthly_spent()
    pct = (spent / budget) * 100

    if pct >= 90:
        logger.error(
            "BUDGET CRITICAL: $%.2f / $%.2f (%.1f%%). "
            "Modelo fallback '%s' activado automáticamente.",
            spent, budget, pct, config.FALLBACK_MODEL
        )
        return "critical"
    elif pct >= 70:
        logger.warning(
            "BUDGET WARNING: $%.2f / $%.2f (%.1f%%). "
            "Proyección mensual: $%.2f",
            spent, budget, pct, _project_monthly(spent)
        )
        return "warning"

    logger.debug("Budget OK: $%.2f / $%.2f (%.1f%%)", spent, budget, pct)
    return "ok"


def get_active_model() -> str:
    """
    Retorna el modelo activo según el presupuesto.

    En Ollama: siempre retorna config.DEFAULT_MODEL (son $0).
    En OpenAI: si budget > 90%, retorna FALLBACK_MODEL.
    """
    if config.is_local:
        return config.DEFAULT_MODEL

    status = check_budget_and_warn()
    if status == "critical":
        return config.FALLBACK_MODEL
    return config.DEFAULT_MODEL


def get_budget_status() -> dict:
    """
    Retorna un resumen del estado del budget para el health endpoint.
    """
    if config.is_local:
        return {
            "provider": config.LLM_PROVIDER,
            "status": "disabled",
            "reason": "Ollama local — costo $0",
            "spent_usd": 0.0,
            "budget_usd": 0.0,
            "used_pct": 0.0,
        }

    spent = get_monthly_spent()
    budget = config.MONTHLY_BUDGET_USD
    pct = (spent / budget * 100) if budget > 0 else 0

    return {
        "provider": config.LLM_PROVIDER,
        "status": check_budget_and_warn(),
        "spent_usd": round(spent, 4),
        "budget_usd": budget,
        "used_pct": round(pct, 1),
        "remaining_usd": round(max(budget - spent, 0), 4),
        "active_model": get_active_model(),
    }


def _project_monthly(spent_so_far: float) -> float:
    """Proyecta el gasto total del mes basado en el gasto acumulado hasta hoy."""
    now = datetime.now()
    day_of_month = now.day
    days_in_month = 30  # aproximación
    if day_of_month == 0:
        return spent_so_far
    return (spent_so_far / day_of_month) * days_in_month