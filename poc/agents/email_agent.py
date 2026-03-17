"""
poc/agents/email_agent.py
-------------------------
Agente específico para generación de Emails.
Mapea estrictamente hacia el esquema de Notion.
"""
from typing import Optional, List
from poc.agents.base_agent import BaseAgent, AgentInput

class EmailAgent(BaseAgent):
    content_type = "email"

    def _build_prompt(self, agent_input: AgentInput) -> str:
        sop = agent_input.sop or (
            "Asunto: máx 60 caracteres, usar número o pregunta si es posible. "
            "Preheader: complementa el asunto, máx 90 caracteres. "
            "Cuerpo: intro de 1 oración + 3 tips/puntos + párrafo de cierre. "
            "CTA: un solo botón/link con texto de acción específico. "
            "Tono: profesional pero cercano. Evitar palabras de spam (gratis, URGENTE, etc.)."
        )
        objective = agent_input.extra.get("objective", "Generar interés")
        context_text = agent_input.chunk.get("content", "") if agent_input.chunk else "Sin contexto extraído."

        return f"""Escribe un email completo para newsletter/outreach.

TEMA PRINCIPAL: {agent_input.topic}
OBJETIVO: {objective}
CONTEXTO EXTRAÍDO: {context_text}

INSTRUCCIONES DE FORMATO (SOP):
{sop}

Responde ÚNICAMENTE con JSON, con la siguiente estructura exacta:
{{
  "asunto": "Subject line del email",
  "preheader": "Texto de previsualización (max 90 chars)",
  "cuerpo": "Cuerpo completo del email con saludo, desarrollo y cierre",
  "cta": "Texto del botón o link final",
  "ps": "Posdata opcional (puede ser vacio)"
}}
"""

    def _parse_response(self, response: str) -> dict:
        data = self.client.parse_json_response(response)
        if not data:
            return {}
            
        return {
            "asunto": data.get("asunto", ""),
            "preheader": data.get("preheader", ""),
            "cuerpo": data.get("cuerpo", ""),
            "cta": data.get("cta", ""),
            "ps": data.get("ps", "")
        }

    def _extra_validations(self, data: dict, agent_input: AgentInput) -> List[str]:
        errors = []
        if not data.get("asunto"):
            errors.append("Falta propiedad 'asunto'")
        if not data.get("cuerpo"):
            errors.append("Falta propiedad 'cuerpo'")
        if len(data.get("asunto", "")) > 100:
            errors.append("El asunto supera los 100 caracteres")
        return errors
