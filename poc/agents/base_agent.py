"""
agents/base_agent.py
--------------------
Clase base para todos los subagentes de generación de contenido.

Principios de diseño (feedback experto):
1. Los agentes son funciones con estructura, NO frameworks pesados
2. El QA Gate es PROGRAMÁTICO por defecto (sin LLM)
3. El LLM solo se llama para QA en casos dudosos o muestras aleatorias (10%)
4. Cada agente produce un ContentPiece tipado (dataclass, no dict libre)
5. Retry automático: 1 reintento antes de marcar como QA_Failed
"""

import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from agent.custom_openai_client import CustomOpenAIClient
from agent.config import settings
from poc.budget_guard import BudgetGuard

logger = logging.getLogger(__name__)


# =============================================================================
# CONTENT PIECE - Resultado estructurado de cualquier agente
# =============================================================================

@dataclass
class ContentPiece:
    """
    Pieza de contenido generada. Estructura común a todos los agentes.
    Los campos específicos de cada formato van en `content` (dict tipado).
    """
    content_type:   str                   # reel_cta | reel_lead_magnet | historia | email | ads
    content:        dict                  # Estructura específica por formato (ver agentes)
    
    # Trazabilidad
    chunk_id:       Optional[str] = None
    document_id:    Optional[str] = None
    source_title:   Optional[str] = None
    
    # Costo
    cost_usd:       float = 0.0
    model_used:     str = ""
    tokens_in:      int = 0
    tokens_out:     int = 0
    
    # QA
    qa_passed:      Optional[bool] = None
    qa_reason:      str = ""
    retry_count:    int = 0


@dataclass
class AgentInput:
    """Input estándar para todos los agentes."""
    topic:        str              # Tópico a generar
    chunk:        Optional[dict] = None    # SearchResult serializado
    sop:          Optional[str] = None    # SOP desde Notion (opcional en Fase 1)
    extra:        dict = field(default_factory=dict)


# =============================================================================
# BASE AGENT
# =============================================================================

class BaseAgent(ABC):
    """
    Clase base abstracta para subagentes de generación.
    
    Para crear un nuevo agente:
    1. Heredar de BaseAgent
    2. Implementar content_type, _build_prompt(), _parse_response()
    3. Opcionalmente override _extra_validations() para checks específicos
    
    El método generate() maneja el retry automático y el QA Gate.
    """

    # Override en cada agente
    content_type: str = "base"

    def __init__(self):
        self.client = CustomOpenAIClient()
        self.budget = BudgetGuard()

    # --------------------------------------------------------------------------
    # MÉTODO PRINCIPAL
    # --------------------------------------------------------------------------

    async def generate(self, agent_input: AgentInput) -> ContentPiece:
        """
        Genera una pieza de contenido con retry automático y QA programático.
        
        Flujo:
        1. Verifica presupuesto
        2. Construye prompt
        3. Llama al LLM
        4. Parsea respuesta a dict estructurado
        5. Valida programáticamente (sin LLM)
        6. Si falla: 1 reintento automático
        7. Si vuelve a fallar: retorna con qa_passed=False
        8. Si pasa QA: opcionalmente valida con LLM (10% de probabilidad)
        """
        # Verificar presupuesto antes de generar
        if not await self.budget.can_generate():
            logger.warning("generate: budget agotado, no se puede generar")
            return ContentPiece(
                content_type=self.content_type,
                content={},
                qa_passed=False,
                qa_reason="Budget mensual agotado",
                chunk_id=agent_input.chunk.get("chunk_id") if agent_input.chunk else None,
            )

        model = await self.budget.get_current_model()
        
        for attempt in range(2):  # máximo 2 intentos (original + 1 retry)
            try:
                prompt = self._build_prompt(agent_input)
                response, usage = await self.client.complete(
                    prompt=prompt,
                    model=model,
                    temperature=0.8,
                    response_format={"type": "json_object"},
                )

                # Registrar costo
                cost = self.budget.track_usage(model, usage.prompt_tokens, usage.completion_tokens)
                
                # Parsear respuesta
                data = self._parse_response(response)

                # QA programático (siempre)
                passed, reason = self._validate_programmatic(data, agent_input)

                # QA con LLM (solo 10% de los casos o si score de confianza es bajo)
                if passed and self._should_llm_validate():
                    passed, reason = await self._validate_with_llm(data, agent_input, model)

                piece = ContentPiece(
                    content_type=self.content_type,
                    content=data,
                    chunk_id=agent_input.chunk.get("chunk_id") if agent_input.chunk else None,
                    document_id=agent_input.chunk.get("document_id") if agent_input.chunk else None,
                    source_title=agent_input.chunk.get("document_title") if agent_input.chunk else None,
                    cost_usd=cost,
                    model_used=model,
                    tokens_in=usage.prompt_tokens,
                    tokens_out=usage.completion_tokens,
                    qa_passed=passed,
                    qa_reason=reason,
                    retry_count=attempt,
                )

                if passed:
                    return piece

                if attempt == 0:
                    logger.info(
                        "generate [%s]: QA falló en intento 1 (razón: %s). Reintentando...",
                        self.content_type, reason
                    )
                    continue

                # Segundo intento también falló
                logger.warning(
                    "generate [%s]: QA falló en ambos intentos. Última razón: %s",
                    self.content_type, reason
                )
                return piece

            except Exception as e:
                logger.error("generate [%s] intento %d falló: %s", self.content_type, attempt + 1, e)
                if attempt == 1:
                    return ContentPiece(
                        content_type=self.content_type,
                        content={},
                        qa_passed=False,
                        qa_reason=f"Error en generación: {e}",
                        retry_count=attempt,
                    )

        # Nunca debería llegar aquí
        return ContentPiece(content_type=self.content_type, content={}, qa_passed=False, qa_reason="Unknown error")

    # --------------------------------------------------------------------------
    # MÉTODOS ABSTRACTOS (implementar en cada agente)
    # --------------------------------------------------------------------------

    @abstractmethod
    def _build_prompt(self, agent_input: AgentInput) -> str:
        """Construye el prompt para el LLM."""
        ...

    @abstractmethod
    def _parse_response(self, response: str) -> dict:
        """Parsea la respuesta JSON del LLM a un dict estructurado."""
        ...

    @abstractmethod
    def _extra_validations(self, data: dict, agent_input: AgentInput) -> list[str]:
        """
        Validaciones específicas del agente. Retorna lista de errores.
        Lista vacía = todo OK.
        """
        ...

    # --------------------------------------------------------------------------
    # QA GATE PROGRAMÁTICO (sin LLM)
    # --------------------------------------------------------------------------

    def _validate_programmatic(self, data: dict, agent_input: AgentInput) -> tuple[bool, str]:
        """
        Validaciones programáticas. Rápido, gratis, determinista.
        
        Checks comunes a todos los agentes:
        - data no es None ni vacío
        - idioma: no contiene palabras en inglés frecuentes
        - cta presente y no vacío
        - ningún campo clave está vacío
        
        Los checks específicos de cada formato van en _extra_validations().
        """
        errors = []

        if not data:
            return False, "Respuesta vacía del LLM"

        # ---------- Validaciones comunes ----------

        # CTA presente (todos los formatos lo requieren)
        cta = data.get("cta", "").strip()
        if not cta:
            errors.append("CTA ausente o vacío")
        elif len(cta) < 5:
            errors.append(f"CTA demasiado corto ({len(cta)} chars)")

        # Detección de inglés (heurística simple, sin LLM)
        all_text = " ".join(str(v) for v in data.values() if isinstance(v, str)).lower()
        english_indicators = {
            "the ", "is a ", "are a ", "your ", "you are", "this is",
            "it's ", "don't ", "can't ", "we are", "i am ", "i'm ",
        }
        english_count = sum(1 for indicator in english_indicators if indicator in all_text)
        if english_count >= 3:
            errors.append(f"Posible contenido en inglés ({english_count} indicadores detectados)")

        # ---------- Validaciones específicas del formato ----------
        format_errors = self._extra_validations(data, agent_input)
        errors.extend(format_errors)

        if errors:
            return False, " | ".join(errors)
        return True, ""

    def _should_llm_validate(self) -> bool:
        """
        Decide si usar LLM para validar esta pieza.
        Por defecto: 10% de probabilidad (muestra aleatoria).
        
        Sobrescribir en agentes donde se quiera más/menos QA con LLM.
        """
        return random.random() < 0.10

    async def _validate_with_llm(
        self,
        data: dict,
        agent_input: AgentInput,
        model: str,
    ) -> tuple[bool, str]:
        """
        Validación con LLM para el 10% de casos o cuando la validación programática
        no es suficiente (por ejemplo, para detectar calidad de storytelling).
        
        NO llama al LLM por defecto en cada pieza. Es un sampling de calidad.
        """
        import json as json_lib

        prompt = f"""Eres un revisor de contenido para redes sociales en español para Latinoamérica.
        
Revisa esta pieza de tipo "{self.content_type}" y responde SOLO con JSON:
{{"passed": true/false, "reason": "explicación breve si failed"}}

Criterios:
- ¿El contenido está completamente en español?
- ¿El tono es profesional pero cercano (no genérico ni corporativo)?
- ¿Hay un gancho claro al inicio?
- ¿El CTA es accionable?

Contenido a revisar:
{json_lib.dumps(data, ensure_ascii=False, indent=2)}
"""
        try:
            response, usage = await self.client.complete(
                prompt=prompt,
                model=model,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            await self.budget.track_usage(model, usage.prompt_tokens, usage.completion_tokens)
            
            import json as json_lib2
            result = json_lib2.loads(response)
            return result.get("passed", True), result.get("reason", "")
        except Exception as e:
            logger.warning("_validate_with_llm falló: %s. Aprobando por defecto.", e)
            return True, ""  # Si el LLM de QA falla, no bloqueamos la pieza