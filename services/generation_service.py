"""
Servicio de generación desacoplado de la interfaz.
HOY: llamado desde run_poc.py y Streamlit directamente.
FUTURO: expuesto via FastAPI POST /generate.
"""
import logging
from typing import Optional

from poc.agents.base_agent import ContentAgent, AgentInput, AgentOutput
from poc.agents.registry import get_agent

logger = logging.getLogger(__name__)


class GenerationService:
    """
    Genera una pieza de contenido usando el agente correcto para el formato.

    Uso actual (POC):
        service = GenerationService()
        output = await service.generate("reel_cta", topic="...", context="...", cta="...")

    Uso futuro (FastAPI):
        @app.post("/generate")
        async def generate_endpoint(req: GenerateRequest):
            result = await service.generate(req.formato, **req.params)
            return result
    """

    async def generate(
        self,
        formato: str,
        topic: str,
        context: str,
        sop: Optional[str] = None,
        **kwargs,
    ) -> AgentOutput:
        """
        Args:
            formato: 'reel_cta' | 'reel_lead_magnet' | 'historia' | 'email' | 'ads'
            topic: Tema de la pieza.
            context: Contexto recuperado de la búsqueda (chunks del RAG).
            sop: Texto del SOP (Standard Operating Procedure). Si None, usa el SOP por defecto del agente.
            **kwargs: Parámetros específicos del formato (cta, tone, objective, lead_magnet, etc.)

        Returns:
            AgentOutput con campos estructurados según el formato.
        """
        agent: ContentAgent = get_agent(formato)
        agent_input = AgentInput(
            topic=topic,
            context=context,
            sop=sop,
            extra=kwargs,
        )
        return await agent.run(agent_input)
