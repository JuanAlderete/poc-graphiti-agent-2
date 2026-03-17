"""
poc/agents/ads_agent.py
-----------------------
Agente específico para generación de anuncios publicitarios (Meta/Google).
Mapea estrictamente hacia el esquema de Notion.
"""
from typing import Optional, List
from poc.agents.base_agent import BaseAgent, AgentInput

class AdsAgent(BaseAgent):
    content_type = "ads"

    def _build_prompt(self, agent_input: AgentInput) -> str:
        sop = agent_input.sop or (
            "Headlines: máx 30 chars c/u, usar número o pregunta. "
            "Descripciones: máx 90 chars c/u, incluir beneficio concreto. "
            "Copy principal: 1-3 párrafos, empezar con el pain point. "
            "CTA: usar verbos de acción (Descubrir, Empezar, Ver, etc.). "
            "Tipo awareness: enfocarse en el problema. "
            "Tipo conversion: enfocarse en la solución + urgencia."
        )
        ad_type = agent_input.extra.get("tipo", "awareness")
        context_text = agent_input.chunk.get("content", "") if agent_input.chunk else "Sin contexto extraído."

        return f"""Crea el copy completo para un anuncio pagado.

TEMA PRINCIPAL: {agent_input.topic}
TIPO DE ANUNCIO: {ad_type}
CONTEXTO EXTRAÍDO: {context_text}

INSTRUCCIONES DE FORMATO (SOP):
{sop}

Responde ÚNICAMENTE con JSON, con la siguiente estructura exacta:
{{
  "headlines": ["Headline 1 (max 30 chars)", "Headline 2", "Headline 3"],
  "descripciones": ["Descripción 1 (max 90 chars)", "Descripción 2"],
  "copy": "Texto principal del anuncio (1-3 párrafos)",
  "cta": "Texto del botón CTA",
  "visual": "Descripción de imagen/video sugerido para el anuncio"
}}
"""

    def _parse_response(self, response: str) -> dict:
        data = self.client.parse_json_response(response)
        if not data:
            return {}
            
        headlines_combined = "\n".join(data.get("headlines", [])) if isinstance(data.get("headlines"), list) else str(data.get("headlines", ""))
        descripciones_combined = "\n".join(data.get("descripciones", [])) if isinstance(data.get("descripciones"), list) else str(data.get("descripciones", ""))

        return {
            "headlines": headlines_combined,
            "descripciones": descripciones_combined,
            "copy": data.get("copy", ""),
            "cta": data.get("cta", ""),
            "visual": data.get("visual", "")
        }

    def _extra_validations(self, data: dict, agent_input: AgentInput) -> List[str]:
        errors = []
        if not data.get("headlines") or len(str(data.get("headlines", ""))) < 5:
            errors.append("Faltan propiedad 'headlines' o es excesivamente corta")
        if not data.get("copy"):
            errors.append("Falta propiedad 'copy' (Cuerpo principal vacío)")
        return errors
