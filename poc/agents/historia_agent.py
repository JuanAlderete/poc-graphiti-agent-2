"""Agente para secuencias de Instagram Stories."""
from poc.agents.base_agent import ContentAgent, AgentInput


class HistoriaAgent(ContentAgent):
    format_name = "historia"
    default_sop = (
        "La secuencia debe tener entre 5 y 7 slides. "
        "Slide 1: Hook visual con pregunta o stat impactante. "
        "Slides 2-5: Contenido educativo o narrativo, un punto por slide. "
        "Último slide: CTA claro. "
        "Máx 30 palabras por slide. Usar emojis con moderación (máx 2 por slide)."
    )

    def _get_system_prompt(self) -> str:
        return (
            "Eres un experto en narrativa para Instagram Stories. "
            "SIEMPRE respondes ÚNICAMENTE con un objeto JSON válido, sin texto adicional."
        )

    def _build_prompt(self, agent_input: AgentInput, sop: str) -> str:
        tone = agent_input.extra.get("tone", "Educativo y cercano")
        tipo = agent_input.extra.get("tipo", "educativa")
        return f"""Crea una secuencia de Instagram Stories sobre el siguiente tema.

TEMA: {agent_input.topic}
TIPO DE HISTORIA: {tipo}
TONO: {tone}

CONTEXTO EXTRAÍDO DE DOCUMENTOS REALES:
{agent_input.context}

INSTRUCCIONES DE ESTILO (SOP):
{sop}

Responde ÚNICAMENTE con este JSON:
{{
  "tipo": "{tipo}",
  "slides": [
    {{
      "numero": 1,
      "texto": "Texto del slide",
      "sugerencia_visual": "Descripción de imagen/video/color de fondo sugerido"
    }}
  ],
  "cta_final": "CTA del último slide",
  "hashtags": ["hashtag1", "hashtag2"]
}}

Incluir entre 5 y 7 slides."""

    def _parse_output(self, raw_text: str) -> dict:
        data = self._safe_json_parse(raw_text)
        data.setdefault("slides", [])
        data.setdefault("cta_final", "")
        data.setdefault("hashtags", [])
        return data

    def _validate(self, data: dict, agent_input: AgentInput) -> tuple[bool, str]:
        slides = data.get("slides", [])
        if len(slides) < 3:
            return False, f"Too few slides: {len(slides)}"
        if not data.get("cta_final"):
            return False, "Missing CTA final"
        return True, ""
