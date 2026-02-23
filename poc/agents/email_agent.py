"""Agente para emails de newsletter/cold email."""
from poc.agents.base_agent import ContentAgent, AgentInput


class EmailAgent(ContentAgent):
    format_name = "email"
    default_sop = (
        "Asunto: máx 60 caracteres, usar número o pregunta si es posible. "
        "Preheader: complementa el asunto, máx 90 caracteres. "
        "Cuerpo: intro de 1 oración + 3 tips/puntos + párrafo de cierre. "
        "CTA: un solo botón/link con texto de acción específico. "
        "Tono: profesional pero cercano. Evitar palabras de spam (gratis, URGENTE, etc.)."
    )

    def _get_system_prompt(self) -> str:
        return (
            "Eres un experto en email marketing con alta tasa de apertura y conversión. "
            "SIEMPRE respondes ÚNICAMENTE con un objeto JSON válido, sin texto adicional."
        )

    def _build_prompt(self, agent_input: AgentInput, sop: str) -> str:
        objective = agent_input.extra.get("objective", "Generar interés")
        return f"""Escribe un email completo para newsletter/outreach sobre el siguiente tema.

TEMA: {agent_input.topic}
OBJETIVO: {objective}

CONTEXTO EXTRAÍDO DE DOCUMENTOS REALES:
{agent_input.context}

INSTRUCCIONES DE ESTILO (SOP):
{sop}

Responde ÚNICAMENTE con este JSON:
{{
  "asunto": "Subject line del email",
  "preheader": "Texto de previsualización (max 90 chars)",
  "cuerpo": "Cuerpo completo del email con saludo, desarrollo y cierre",
  "cta_texto": "Texto exacto del botón/link de CTA",
  "cta_descripcion": "A dónde lleva o qué acción genera el CTA",
  "ps": "Postscript opcional (puede ser vacío)"
}}"""

    def _parse_output(self, raw_text: str) -> dict:
        data = self._safe_json_parse(raw_text)
        for key in ["asunto", "preheader", "cuerpo", "cta_texto", "cta_descripcion", "ps"]:
            data.setdefault(key, "")
        return data

    def _validate(self, data: dict, agent_input: AgentInput) -> tuple[bool, str]:
        if not data.get("asunto"):
            return False, "Missing asunto"
        if not data.get("cuerpo"):
            return False, "Missing cuerpo"
        if len(data.get("asunto", "")) > 100:
            return False, "Asunto too long"
        return True, ""
