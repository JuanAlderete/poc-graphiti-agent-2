"""Registro de agentes por formato. Agregar nuevos agentes aquí."""
from poc.agents.reel_cta_agent import ReelCTAAgent
from poc.agents.historia_agent import HistoriaAgent
from poc.agents.email_agent import EmailAgent
from poc.agents.reel_lead_magnet_agent import ReelLeadMagnetAgent
from poc.agents.ads_agent import AdsAgent
from poc.agents.base_agent import ContentAgent

_REGISTRY: dict[str, ContentAgent] = {
    "reel_cta": ReelCTAAgent(),
    "historia": HistoriaAgent(),
    "email": EmailAgent(),
    "reel_lead_magnet": ReelLeadMagnetAgent(),
    "ads": AdsAgent(),
}


def get_agent(formato: str) -> ContentAgent:
    """
    Retorna el agente para el formato solicitado.
    Lanza ValueError si el formato no existe.
    """
    agent = _REGISTRY.get(formato)
    if agent is None:
        available = list(_REGISTRY.keys())
        raise ValueError(f"Unknown format '{formato}'. Available: {available}")
    return agent


def list_formats() -> list[str]:
    """Retorna la lista de formatos disponibles."""
    return list(_REGISTRY.keys())
