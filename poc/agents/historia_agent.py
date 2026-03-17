"""
poc/agents/historia_agent.py
----------------------------
Agente específico para generación de Historias.
Mapea estrictamente hacia el esquema de Notion.
"""
from typing import Optional, List
from poc.agents.base_agent import BaseAgent, AgentInput

class HistoriaAgent(BaseAgent):
    content_type = "historia"

    def _build_prompt(self, agent_input: AgentInput) -> str:
        sop = agent_input.sop or (
            "La secuencia debe tener entre 5 y 7 slides. "
            "Slide 1: Hook visual con pregunta o stat impactante. "
            "Slides 2-5: Contenido educativo o narrativo, un punto por slide. "
            "Último slide: CTA claro. "
            "Máx 30 palabras por slide. Usar emojis con moderación (máx 2 por slide)."
        )
        
        tone = agent_input.extra.get("tone", "Educativo y cercano")
        tipo = agent_input.extra.get("tipo", "educativa")
        context_text = agent_input.chunk.get("content", "") if agent_input.chunk else "Sin contexto extraído."

        return f"""Crea una secuencia de Instagram Stories.

TEMA PRINCIPAL: {agent_input.topic}
TIPO DE HISTORIA: {tipo}
TONO: {tone}
CONTEXTO EXTRAÍDO: {context_text}

INSTRUCCIONES DE FORMATO (SOP):
{sop}

Responde ÚNICAMENTE con JSON, con la siguiente estructura exacta:
{{
  "tipo": "{tipo}",
  "slides": [
    {{
      "numero": 1,
      "texto": "Texto del slide",
      "sugerencia_visual": "Descripción sugerida de la imagen"
    }}
  ],
  "cta_final": "El llamado a la acción exacto requerido"
}}
"""

    def _parse_response(self, response: str) -> dict:
        data = self.client.parse_json_response(response)
        if not data:
            return {}
            
        slides = data.get("slides", [])
        # Combinar el texto de todos los slides para insertarlo facil en Notion (String) o como convenga
        try:
            slides_combined = "\n\n".join([f"Slide {s.get('numero', i+1)}: {s.get('texto', '')} | [Visual: {s.get('sugerencia_visual', '')}]" for i, s in enumerate(slides)])
        except Exception:
            slides_combined = str(slides)

        return {
            "tipo": data.get("tipo", ""),
            "slides": slides_combined,
            "cta_final": data.get("cta_final", "")
        }

    def _extra_validations(self, data: dict, agent_input: AgentInput) -> List[str]:
        errors = []
        if not data.get("slides") or data.get("slides") == "[]" or len(str(data.get("slides"))) < 20:
             errors.append("Secuencia de slides muy corta o vacía")
        if not data.get("cta_final"):
            errors.append("Falta propiedad 'cta_final'")
        return errors
