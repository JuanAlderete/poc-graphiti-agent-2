"""
Control de presupuesto mensual.

Persiste el gasto del mes actual en un archivo JSON simple.
Cuando se supera el 90%, activa el modelo fallback automáticamente.

Diseño thread-safe: usa threading.Lock para escrituras al archivo.

PUNTO DE MIGRACIÓN FASE 1:
    Reemplazar el archivo JSON por una tabla en Postgres:
        CREATE TABLE monthly_budget_tracking (
            month DATE PRIMARY KEY,
            spent_usd FLOAT DEFAULT 0,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    El resto de la lógica (alertas, fallback) no cambia.
"""
import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from agent.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _get_current_month() -> str:
    """Retorna 'YYYY-MM' del mes actual."""
    return datetime.now().strftime("%Y-%m")


def _load_tracking() -> dict:
    """Carga el archivo de tracking. Retorna dict vacío si no existe."""
    path = Path(settings.BUDGET_TRACKING_FILE)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning("Could not load budget tracking file, starting fresh.")
        return {}


def _save_tracking(data: dict) -> None:
    """Guarda el archivo de tracking."""
    path = Path(settings.BUDGET_TRACKING_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_monthly_spent() -> float:
    """Retorna el gasto total del mes actual en USD."""
    with _lock:
        data = _load_tracking()
        month = _get_current_month()
        return float(data.get(month, {}).get("spent_usd", 0.0))


def record_cost(cost_usd: float) -> None:
    """
    Registra un costo en el tracking mensual.
    Llama a esta función después de cada operación LLM.
    """
    if settings.MONTHLY_BUDGET_USD <= 0:
        return  # Budget control disabled

    with _lock:
        data = _load_tracking()
        month = _get_current_month()

        if month not in data:
            data[month] = {"spent_usd": 0.0, "operations": 0}

        data[month]["spent_usd"] = round(data[month]["spent_usd"] + cost_usd, 6)
        data[month]["operations"] = data[month].get("operations", 0) + 1
        data[month]["last_updated"] = datetime.now().isoformat()

        _save_tracking(data)

    # Check budget AFTER releasing lock to avoid deadlock
    check_budget_and_warn()


def check_budget_and_warn() -> str:
    """
    Verifica el estado del presupuesto y emite alertas.

    Returns:
        'ok' | 'warning' | 'critical' | 'disabled'
    """
    if settings.MONTHLY_BUDGET_USD <= 0:
        return "disabled"

    spent = get_monthly_spent()
    budget = settings.MONTHLY_BUDGET_USD
    pct = (spent / budget) * 100 if budget > 0 else 0

    if pct >= 90:
        logger.error(
            "BUDGET CRITICAL: $%.2f / $%.2f (%.1f%%). "
            "Fallback model '%s' is now active. "
            "Update MONTHLY_BUDGET_USD in .env to resume normal operation.",
            spent, budget, pct, settings.FALLBACK_MODEL
        )
        return "critical"
    elif pct >= 70:
        logger.warning(
            "BUDGET WARNING: $%.2f / $%.2f (%.1f%%). "
            "Projected monthly spend: $%.2f. "
            "Consider reviewing cost-intensive operations.",
            spent, budget, pct, _project_monthly(spent)
        )
        return "warning"
    else:
        logger.debug("Budget OK: $%.2f / $%.2f (%.1f%%)", spent, budget, pct)
        return "ok"


def get_active_model() -> str:
    """
    Retorna el modelo activo según el estado del presupuesto.
    Si está en critical (>90%), retorna el FALLBACK_MODEL.
    En todos los demás casos, retorna DEFAULT_MODEL.
    """
    status = check_budget_and_warn()
    if status == "critical":
        return settings.FALLBACK_MODEL
    return settings.DEFAULT_MODEL


def get_budget_summary() -> dict:
    """Retorna un resumen del presupuesto para mostrar en el dashboard."""
    spent = get_monthly_spent()
    budget = settings.MONTHLY_BUDGET_USD
    pct = (spent / budget * 100) if budget > 0 else 0
    status = check_budget_and_warn()

    return {
        "month": _get_current_month(),
        "spent_usd": round(spent, 4),
        "budget_usd": budget,
        "percentage": round(pct, 1),
        "status": status,
        "active_model": get_active_model(),
        "fallback_active": status == "critical",
        "projected_monthly": round(_project_monthly(spent), 2),
    }


def _project_monthly(spent_so_far: float) -> float:
    """Proyecta el gasto total del mes basado en el gasto hasta ahora."""
    now = datetime.now()
    days_elapsed = now.day
    days_in_month = 30  # aproximación
    if days_elapsed == 0:
        return spent_so_far
    daily_rate = spent_so_far / days_elapsed
    return daily_rate * days_in_month
