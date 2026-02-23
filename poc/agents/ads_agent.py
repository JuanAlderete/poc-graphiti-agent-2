"""Agente para anuncios pagados (Meta Ads / Google Ads)."""
from poc.agents.base_agent import ContentAgent, AgentInput


class AdsAgent(ContentAgent):
    format_name = "ads"
    default_sop = (
        "Headlines: máx 30 chars c/u, usar número o pregunta. "
        "Descripciones: máx 90 chars c/u, incluir beneficio concreto. "
        "Copy principal: 1-3 párrafos, empezar con el pain point. "
        "CTA: usar verbos de acción (Descubrir, Empezar, Ver, etc.). "
        "Tipo awareness: enfocarse en el problema. "
        "Tipo conversion: enfocarse en la solución + urgencia."
    )

    def _get_system_prompt(self) -> str:
        return (
            "Eres un especialista en publicidad digital con alto ROAS. "
            "SIEMPRE respondes ÚNICAMENTE con un objeto JSON válido, sin texto adicional."
        )

    def _build_prompt(self, agent_input: AgentInput, sop: str) -> str:
        ad_type = agent_input.extra.get("tipo", "awareness")
        return f"""Crea el copy completo para un anuncio de {ad_type.upper()}.

TEMA: {agent_input.topic}
TIPO DE ANUNCIO: {ad_type}

CONTEXTO EXTRAÍDO DE DOCUMENTOS REALES:
{agent_input.context}

INSTRUCCIONES DE ESTILO (SOP):
{sop}

Responde ÚNICAMENTE con este JSON:
{{
  "tipo": "{ad_type}",
  "headlines": ["Headline 1 (max 30 chars)", "Headline 2 (max 30 chars)", "Headline 3 (max 30 chars)"],
  "descripciones": ["Descripción 1 (max 90 chars)", "Descripción 2 (max 90 chars)"],
  "copy_principal": "Texto principal del anuncio (1-3 párrafos)",
  "cta": "Texto del botón CTA",
  "sugerencia_visual": "Descripción de imagen o video sugerido para el anuncio"
}}"""

    def _parse_output(self, raw_text: str) -> dict:
        data = self._safe_json_parse(raw_text)
        data.setdefault("headlines", [])
        data.setdefault("descripciones", [])
        data.setdefault("copy_principal", "")
        data.setdefault("cta", "")
        data.setdefault("sugerencia_visual", "")
        return data

    def _validate(self, data: dict, agent_input: AgentInput) -> tuple[bool, str]:
        if len(data.get("headlines", [])) < 2:
            return False, "Need at least 2 headlines"
        if not data.get("copy_principal"):
            return False, "Missing copy principal"
        for h in data.get("headlines", []):
            if len(h) > 35:
                return False, f"Headline too long: '{h}'"
        return True, ""
