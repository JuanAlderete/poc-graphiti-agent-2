"""Agente para Reels tipo Lead Magnet."""
from poc.agents.base_agent import ContentAgent, AgentInput


class ReelLeadMagnetAgent(ContentAgent):
    format_name = "reel_lead_magnet"
    default_sop = (
        "El reel debe presentar el problema, mostrar el recurso gratuito como solución, "
        "y generar urgencia para que el espectador lo busque. "
        "Mencionar el lead magnet de forma concreta (nombre + qué incluye). "
        "CTA debe mencionar dónde obtenerlo (link en bio, DM, etc.)."
    )

    def _get_system_prompt(self) -> str:
        return (
            "Eres un experto en marketing de contenidos y generación de leads. "
            "SIEMPRE respondes ÚNICAMENTE con un objeto JSON válido, sin texto adicional."
        )

    def _build_prompt(self, agent_input: AgentInput, sop: str) -> str:
        lead_magnet = agent_input.extra.get("lead_magnet", "recurso gratuito")
        return f"""Crea un guion para un Reel que promueva un lead magnet.

TEMA: {agent_input.topic}
LEAD MAGNET A PROMOCIONAR: {lead_magnet}

CONTEXTO EXTRAÍDO DE DOCUMENTOS REALES:
{agent_input.context}

INSTRUCCIONES DE ESTILO (SOP):
{sop}

Responde ÚNICAMENTE con este JSON:
{{
  "hook": "Primeros 3 segundos (máx 15 palabras)",
  "problema": "Pain point que el lead magnet resuelve",
  "presentacion_lm": "Cómo presentar el recurso y qué incluye",
  "cta": "CTA específico con dónde obtener el recurso",
  "sugerencias_grabacion": "Tips de producción para este tipo de reel"
}}"""

    def _parse_output(self, raw_text: str) -> dict:
        data = self._safe_json_parse(raw_text)
        for key in ["hook", "problema", "presentacion_lm", "cta", "sugerencias_grabacion"]:
            data.setdefault(key, "")
        return data

    def _validate(self, data: dict, agent_input: AgentInput) -> tuple[bool, str]:
        if not data.get("hook"):
            return False, "Missing hook"
        if not data.get("cta"):
            return False, "Missing CTA"
        return True, ""
