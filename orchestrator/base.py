"""
orchestrator/base.py
--------------------
Clase abstracta base para los diferentes jobs del orquestador.
(Ej. WeeklyContentJob, MasterclassJob, etc.)
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any


class JobType(ABC):
    """
    Define la estructura básica que debe cumplir un job de generación (Orchestrator).
    """
    @abstractmethod
    async def get_requirements(self) -> List[Dict[str, Any]]:
        """
        Retorna la lista de requisitos.
        Ejemplo: [{"formato": "reel_cta", "cantidad": 5, "topico": "Ventas"}]
        """
        pass

    def generate_search_intents(self, topic: str) -> List[str]:
        """
        Genera ángulos de búsqueda (Search Intents) basados en un tópico.
        En MVP (Fase 1) retorna variaciones hardcodeadas síncronas sin LLM, 
        igual que el fallback que existía en generate.py original.
        """
        return [
            topic,
            f"objeciones y miedos de {topic}",
            f"ejemplos prácticos de {topic}",
            f"errores comunes al aplicar {topic}",
            f"paso a paso de {topic}"
        ]

    @abstractmethod
    def get_subagents(self) -> List[str]:
        """
        Retorna la lista de nombres/identificadores de agentes permitidos para este job.
        """
        pass
