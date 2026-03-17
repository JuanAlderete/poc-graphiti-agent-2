"""
poc/agents/reel_lead_magnet_agent.py
------------------------------------
Agente específico para generación de Reels Lead Magnet.
Mapea estrictamente hacia el esquema de Notion.
"""
from typing import Optional, List
from poc.agents.base_agent import BaseAgent, AgentInput

class ReelLeadMagnetAgent(BaseAgent):
    content_type = "reel_lead_magnet"

    def _build_prompt(self, agent_input: AgentInput) -> str:
        sop = agent_input.sop or (
            "El reel debe presentar el problema, mostrar el recurso gratuito como solución, "
            "y generar urgencia para que el espectador lo busque. "
            "Mencionar el lead magnet de forma concreta (nombre + qué incluye). "
            "CTA debe mencionar dónde obtenerlo (link en bio, DM, etc.)."
        )
        lead_magnet = agent_input.extra.get("lead_magnet", "recurso gratuito estándar")
        context_text = agent_input.chunk.get("content", "") if agent_input.chunk else "Sin contexto extraído."

        return f"""Crea un guion para un Reel promocionando un Lead Magnet.

TEMA PRINCIPAL: {agent_input.topic}
LEAD MAGNET A PROMOCIONAR: {lead_magnet}
CONTEXTO EXTRAÍDO: {context_text}

INSTRUCCIONES DE FORMATO (SOP):
{sop}

Responde ÚNICAMENTE con JSON, con la siguiente estructura exacta:
{{
  "hook": "Primeros 3 segundos de enganche (máx 15 palabras)",
  "problema": "Pain point que el lead magnet resuelve",
  "presentacion_lm": "Cómo presentar el recurso y qué incluye específicamente",
  "cta": "Llamado a la acción con indicaciones de obtención",
  "sugerencias_grabacion": "Tips de producción en encuadres y dinámicas visuales",
  "copy": "Texto para poner en la descripción del Reel"
}}
"""

    def _parse_response(self, response: str) -> dict:
        data = self.client.parse_json_response(response)
        if not data:
            return {}
            
        return {
            "hook": data.get("hook", ""),
            "problema": data.get("problema", ""),
            "presentacion_lm": data.get("presentacion_lm", ""),
            "cta": data.get("cta", ""),
            "sugerencias_grabacion": data.get("sugerencias_grabacion", ""),
            "copy": data.get("copy", "")
        }

    def _extra_validations(self, data: dict, agent_input: AgentInput) -> List[str]:
        errors = []
        if not data.get("hook"):
            errors.append("Falta propiedad 'hook'")
        if not data.get("presentacion_lm"):
            errors.append("Falta propiedad 'presentacion_lm'")
        if not data.get("cta"):
            errors.append("Falta propiedad 'cta'")
        return errors
