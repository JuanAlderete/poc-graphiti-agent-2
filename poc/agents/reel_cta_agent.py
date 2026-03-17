"""
poc/agents/reel_cta_agent.py
----------------------------
Agente específico para generación de Reels CTA.
Mapea estrictamente hacia el esquema de Notion.
"""
from typing import Optional, List
from poc.agents.base_agent import BaseAgent, AgentInput

class ReelCTAAgent(BaseAgent):
    content_type = "reel_cta"
    
    def _build_prompt(self, agent_input: AgentInput) -> str:
        # SOP es pasado en agent_input.sop. Si no existe un fallback
        sop = agent_input.sop or (
            "El reel debe enganchar en los primeros 3 segundos con una pregunta o afirmación fuerte. "
            "Usar lenguaje conversacional, directo. El CTA debe ser claro y único. "
            "Máximo 45 segundos de guion (aprox 120 palabras). "
            "Hablar en segunda persona (tú/vos)."
        )
        cta_req = agent_input.extra.get("cta", "Call to Action Específico desde Topic")
        
        # El context debe extraerse del chunk dictionary de manera tolerante a faltas
        context_text = agent_input.chunk.get("content", "") if agent_input.chunk else "Sin contexto extraído."

        return f"""Crea un guion completo para un Reel de Instagram.

TEMA PRINCIPAL: {agent_input.topic}
CONTEXTO EXTRAÍDO: {context_text}
CTA ESPERADO: {cta_req}

INSTRUCCIONES DE FORMATO (SOP):
{sop}

Responde ÚNICAMENTE con JSON, con la siguiente estructura exacta:
{{
  "hook": "Los primeros 3 segundos (máx 15 palabras)",
  "script": "Cuerpo completo del guion con solución o insight",
  "cta": "El llamado a la acción exacto requerido",
  "sugerencias_grabacion": "Tips de Producción",
  "copy": "Texto para poner en la descripción del Reel"
}}
"""

    def _parse_response(self, response: str) -> dict:
        data = self.client.parse_json_response(response)
        if not data:
            return {}
            
        # Homologar propiedades con el schema notion_schema "reel_cta"
        return {
            "hook": data.get("hook", ""),
            "script": data.get("script", ""),
            "cta": data.get("cta", ""),
            "sugerencias_grabacion": data.get("sugerencias_grabacion", ""),
            "copy": data.get("copy", "")
        }

    def _extra_validations(self, data: dict, agent_input: AgentInput) -> List[str]:
        errors = []
        if not data.get("hook"):
            errors.append("Falta propiedad 'hook'")
        if not data.get("script"):
            errors.append("Falta propiedad 'script' (Guion vacío)")
        if len(data.get("hook", "")) > 200:
            errors.append("Hook supera los 200 caracteres")
            
        return errors
