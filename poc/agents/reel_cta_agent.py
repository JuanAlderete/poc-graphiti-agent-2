"""Agente para Reels con CTA (Call to Action)."""
from poc.agents.base_agent import ContentAgent, AgentInput


class ReelCTAAgent(ContentAgent):
    format_name = "reel_cta"
    default_sop = (
        "El reel debe enganchar en los primeros 3 segundos con una pregunta o afirmación fuerte. "
        "Usar lenguaje conversacional, directo. El CTA debe ser claro y único. "
        "Máximo 45 segundos de guion (aprox 120 palabras). "
        "No usar jerga técnica. Hablar en segunda persona (tú/vos)."
    )

    def _get_system_prompt(self) -> str:
        return (
            "Eres un guionista experto en Reels y TikToks virales para el mercado hispanohablante. "
            "SIEMPRE respondes ÚNICAMENTE con un objeto JSON válido, sin texto adicional, sin markdown."
        )

    def _build_prompt(self, agent_input: AgentInput, sop: str) -> str:
        cta = agent_input.extra.get("cta", "Sígueme para más contenido")
        return f"""Crea un guion completo para un Reel de Instagram sobre el siguiente tema.

TEMA: {agent_input.topic}

CONTEXTO EXTRAÍDO DE DOCUMENTOS REALES:
{agent_input.context}

CTA REQUERIDO: {cta}

INSTRUCCIONES DE ESTILO (SOP):
{sop}

Responde ÚNICAMENTE con este JSON (sin texto extra, sin ```json```):
{{
  "hook": "Los primeros 3 segundos que enganchen al espectador (máx 15 palabras)",
  "problema": "El pain point que el reel aborda (1-2 oraciones)",
  "desarrollo": "Cuerpo del guion con la solución o insight principal (3-5 oraciones)",
  "cta": "Llamado a la acción final exacto",
  "sugerencias_grabacion": "Tips de producción: toma, luz, velocidad de cortes",
  "copy_descripcion": "Texto para poner en la descripción del reel (máx 150 chars)"
}}"""

    def _parse_output(self, raw_text: str) -> dict:
        data = self._safe_json_parse(raw_text)
        # Normalizar claves esperadas
        for key in ["hook", "problema", "desarrollo", "cta", "sugerencias_grabacion", "copy_descripcion"]:
            data.setdefault(key, "")
        return data

    def _validate(self, data: dict, agent_input: AgentInput) -> tuple[bool, str]:
        if not data.get("hook"):
            return False, "Missing hook"
        if not data.get("cta"):
            return False, "Missing CTA"
        if len(data.get("hook", "")) > 200:
            return False, "Hook too long"
        return True, ""
