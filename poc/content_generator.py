import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

import google.generativeai as genai
from openai import AsyncOpenAI

from agent.config import settings
from poc.logging_utils import generation_logger
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)

# Limites para modelos NO reasoning (gpt-4o-mini, etc.)
_MAX_TOKENS_DEFAULT = 600
_MAX_TOKENS_BY_FORMAT = {
    "email": 300,
    "reel_cta": 250,
    "reel_lead_magnet": 300,
    "historia": 500,
}

# FIX P3: Para reasoning models (gpt-5-*, o1-*), usar un budget alto.
# El reasoning consume 1000-2000 tokens para prompts de generacion.
# El output deseado (email, reel) es ~300-500 tokens.
# Total necesario: ~2500 tokens -> 3000 da margen seguro.
_MAX_TOKENS_REASONING_GEN = 3000


class ContentGenerator(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        *,
        formato: str = "text",
        tema: str = "unknown",
        max_tokens: Optional[int] = None,
    ) -> str:
        """Genera contenido y registra uso. Retorna el string generado."""


class OpenAIContentGenerator(ContentGenerator):
    def __init__(self) -> None:
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.DEFAULT_MODEL

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        *,
        formato: str = "text",
        tema: str = "unknown",
        max_tokens: Optional[int] = None,
    ) -> str:
        start_time = time.time()
        op_id = f"gen_openai_{start_time:.3f}"
        tracker.start_operation(op_id, "generation_openai")

        # gpt-5-* y o1-* son reasoning models
        is_reasoning = self.model.startswith("o1-") or self.model.startswith("gpt-5")

        if max_tokens:
            token_limit = max_tokens
        elif is_reasoning:
            # FIX P3: budget alto para reasoning models en generacion
            token_limit = _MAX_TOKENS_REASONING_GEN
        else:
            token_limit = _MAX_TOKENS_BY_FORMAT.get(formato, _MAX_TOKENS_DEFAULT)

        try:
            messages = []
            if system_prompt and system_prompt.strip():
                messages.append({"role": "system", "content": system_prompt.strip()})
            messages.append({"role": "user", "content": prompt})

            kwargs: dict = {"model": self.model, "messages": messages}
            if is_reasoning:
                kwargs["max_completion_tokens"] = token_limit
            else:
                kwargs["max_tokens"] = token_limit

            response = await self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
            usage = response.usage

            # Log de advertencia si el output sigue vacio (para diagnostico)
            if not content.strip():
                logger.warning(
                    "Generation returned empty content for formato='%s'. "
                    "finish_reason=%s, completion_tokens=%d",
                    formato,
                    response.choices[0].finish_reason,
                    usage.completion_tokens if usage else 0,
                )

            tracker.record_usage(
                op_id, usage.prompt_tokens, usage.completion_tokens,
                self.model, "generation_call",
            )

            latency = time.time() - start_time
            metrics = tracker.end_operation(op_id)
            cost = metrics.cost_usd if metrics else 0.0

            generation_logger.log_row({
                "pieza_id": op_id,
                "timestamp": start_time,
                "formato": formato,
                "tema_base": tema,
                "tokens_contexto_in": 0,
                "tokens_prompt_in": usage.prompt_tokens,
                "tokens_out": usage.completion_tokens,
                "modelo": self.model,
                "provider": "openai",
                "costo_usd": cost,
                "tiempo_seg": latency,
                "longitud_output_chars": len(content),
            })

            return content

        except Exception:
            logger.exception("OpenAI generation failed")
            tracker.end_operation(op_id)
            raise


class GeminiContentGenerator(ContentGenerator):
    def __init__(self) -> None:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model_name = settings.DEFAULT_MODEL

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        *,
        formato: str = "text",
        tema: str = "unknown",
        max_tokens: Optional[int] = None,
    ) -> str:
        start_time = time.time()
        op_id = f"gen_gemini_{start_time:.3f}"
        tracker.start_operation(op_id, "generation_gemini")

        token_limit = max_tokens or _MAX_TOKENS_BY_FORMAT.get(formato, _MAX_TOKENS_DEFAULT)

        try:
            generation_config = genai.types.GenerationConfig(max_output_tokens=token_limit)
            model = genai.GenerativeModel(
                self.model_name,
                system_instruction=(
                    system_prompt.strip()
                    if system_prompt and system_prompt.strip()
                    else None
                ),
                generation_config=generation_config,
            )
            response = await model.generate_content_async(prompt)
            content = response.text or ""

            usage = response.usage_metadata
            p_tokens = getattr(usage, "prompt_token_count", 0) or 0
            c_tokens = getattr(usage, "candidates_token_count", 0) or 0

            tracker.record_usage(op_id, p_tokens, c_tokens, self.model_name, "generation_call")

            latency = time.time() - start_time
            metrics = tracker.end_operation(op_id)
            cost = metrics.cost_usd if metrics else 0.0

            generation_logger.log_row({
                "pieza_id": op_id,
                "timestamp": start_time,
                "formato": formato,
                "tema_base": tema,
                "tokens_contexto_in": 0,
                "tokens_prompt_in": p_tokens,
                "tokens_out": c_tokens,
                "modelo": self.model_name,
                "provider": "gemini",
                "costo_usd": cost,
                "tiempo_seg": latency,
                "longitud_output_chars": len(content),
            })

            return content

        except Exception:
            logger.exception("Gemini generation failed")
            tracker.end_operation(op_id)
            raise


def get_content_generator() -> ContentGenerator:
    """Retorna el ContentGenerator apropiado para el proveedor configurado."""
    if settings.LLM_PROVIDER.lower() == "gemini":
        return GeminiContentGenerator()
    return OpenAIContentGenerator()