"""
Clase base para todos los agentes de generación de contenido.

DISEÑO PARA MIGRACIÓN MÍNIMA A PYDANTIC AI:
El método _call_llm() contiene TODA la lógica de llamada al LLM.
En Fase 1 con Pydantic AI, solo se reemplaza _call_llm() por
un agente Pydantic AI. Todo lo demás (SOP loading, output parsing,
token tracking, logging) se mantiene igual.
"""
import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from agent.config import settings
from poc.logging_utils import generation_logger
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)


@dataclass
class AgentInput:
    """Input estándar para todos los agentes."""
    topic: str
    context: str                    # Chunks del RAG (texto concatenado)
    sop: Optional[str] = None       # SOP override. Si None, usa el SOP por defecto del agente.
    extra: dict = field(default_factory=dict)  # Parámetros adicionales por formato (cta, tone, etc.)


@dataclass
class AgentOutput:
    """Output estándar. El campo `data` contiene el dict con los campos del formato."""
    formato: str
    topic: str
    data: dict                      # Campos estructurados (hook, script, cta, etc.)
    raw_text: str                   # Texto crudo retornado por el LLM (para debug)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    source_reference: Optional[str] = None   # Para trazabilidad
    qa_passed: bool = True
    qa_notes: str = ""


class ContentAgent(ABC):
    """
    Base para agentes de generación de contenido.

    Subclases implementan:
    - format_name: str — identificador del formato
    - output_schema: dict — schema JSON esperado (documentación del output)
    - default_sop: str — SOP por defecto si no se pasa uno
    - _build_prompt(input, sop) → str — construye el prompt completo
    - _parse_output(raw_text) → dict — parsea el JSON retornado
    - _validate(data) → (bool, str) — QA Gate básico
    """

    format_name: str = "base"
    default_sop: str = ""

    # Tokens máximos según tipo de modelo
    _MAX_TOKENS_REASONING = 3000   # gpt-5-*, o1-*
    _MAX_TOKENS_DEFAULT = 800      # gpt-4o-mini y similares

    async def run(self, agent_input: AgentInput) -> AgentOutput:
        """
        Ejecuta el agente completo: SOP loading → build prompt → call LLM → parse → QA.

        Este método NO cambia cuando se migre a Pydantic AI.
        Solo cambia _call_llm().
        """
        start_time = time.time()
        op_id = f"agent_{self.format_name}_{int(start_time * 1000)}"
        tracker.start_operation(op_id, f"generation_{self.format_name}")

        sop = agent_input.sop or self._load_sop()
        prompt = self._build_prompt(agent_input, sop)
        system_prompt = self._get_system_prompt()

        raw_text = ""
        tokens_in = 0
        tokens_out = 0

        try:
            raw_text, tokens_in, tokens_out, model_used = await self._call_llm(prompt, system_prompt)
            tracker.record_usage(op_id, tokens_in, tokens_out, model_used, "generation_call")

            data = self._parse_output(raw_text)
            qa_passed, qa_notes = self._validate(data, agent_input)

        except Exception:
            logger.exception("Agent '%s' failed", self.format_name)
            data = {}
            qa_passed = False
            qa_notes = "Exception during generation"

        latency = time.time() - start_time
        metrics = tracker.end_operation(op_id)
        cost = metrics.cost_usd if metrics else 0.0

        generation_logger.log_row({
            "pieza_id": op_id,
            "timestamp": start_time,
            "formato": self.format_name,
            "tema_base": agent_input.topic,
            "tokens_contexto_in": tracker.estimate_tokens(agent_input.context),
            "tokens_prompt_in": tokens_in,
            "tokens_out": tokens_out,
            "modelo": model_used,
            "provider": settings.LLM_PROVIDER,
            "costo_usd": cost,
            "tiempo_seg": latency,
            "longitud_output_chars": len(raw_text),
        })

        return AgentOutput(
            formato=self.format_name,
            topic=agent_input.topic,
            data=data,
            raw_text=raw_text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            qa_passed=qa_passed,
            qa_notes=qa_notes,
        )

    async def _call_llm(self, prompt: str, system_prompt: str) -> tuple[str, int, int]:
        """
        Llama al LLM y retorna (texto_respuesta, tokens_in, tokens_out).

        PUNTO DE MIGRACIÓN A PYDANTIC AI EN FASE 1:
        Reemplazar este método por un agente Pydantic AI que use el output_schema
        para validar el output directamente. El resto de la clase no cambia.

        Usa el modelo activo según presupuesto (puede ser fallback si budget > 90%).
        """
        from openai import AsyncOpenAI

        # Usar modelo activo según presupuesto (puede ser fallback si budget > 90%)
        try:
            from poc.budget_guard import get_active_model
            active_model = get_active_model()
        except Exception:
            active_model = settings.DEFAULT_MODEL

        is_reasoning = active_model.startswith("o1-") or active_model.startswith("gpt-5")
        token_limit = self._MAX_TOKENS_REASONING if is_reasoning else self._MAX_TOKENS_DEFAULT

        client_kwargs = {"api_key": settings.OPENAI_API_KEY or "ollama"}
        if settings.OPENAI_BASE_URL:
            client_kwargs["base_url"] = settings.OPENAI_BASE_URL
        client = AsyncOpenAI(**client_kwargs)

        messages = []
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})
        messages.append({"role": "user", "content": prompt})

        kwargs = {"model": active_model, "messages": messages}
        if is_reasoning:
            kwargs["max_completion_tokens"] = token_limit
        else:
            kwargs["max_tokens"] = token_limit

        response = await client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content or ""
        usage = response.usage
        return text, tokens_in, tokens_out, active_model

    def _load_sop(self) -> str:
        """
        Carga el SOP desde archivo local (hoy) o Notion API (Fase 1).

        PUNTO DE MIGRACIÓN A NOTION EN FASE 1:
        Reemplazar la lectura del archivo por:
            from storage.notion_client import NotionClient
            client = NotionClient()
            return await client.get_sop_page(self.format_name)
        """
        sop_path = os.path.join("config", "sops", f"{self.format_name}.txt")
        if os.path.exists(sop_path):
            with open(sop_path, encoding="utf-8") as f:
                return f.read().strip()
        return self.default_sop

    @abstractmethod
    def _get_system_prompt(self) -> str:
        ...

    @abstractmethod
    def _build_prompt(self, agent_input: AgentInput, sop: str) -> str:
        ...

    @abstractmethod
    def _parse_output(self, raw_text: str) -> dict:
        ...

    def _validate(self, data: dict, agent_input: AgentInput) -> tuple[bool, str]:
        """QA Gate básico. Sobreescribir en subclases para validaciones específicas."""
        if not data:
            return False, "Empty output"
        return True, ""

    def _safe_json_parse(self, raw_text: str) -> dict:
        """Parsea JSON con fallback. Maneja texto con markdown code blocks."""
        text = raw_text.strip()
        # Quitar ```json ... ``` si el LLM los incluyó
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Último intento: buscar el primer { ... } válido
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            logger.warning("Could not parse JSON from LLM output: %s...", text[:200])
            return {"raw": raw_text}
