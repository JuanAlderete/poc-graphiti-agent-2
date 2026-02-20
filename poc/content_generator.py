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

class ContentGenerator(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        *,
        formato: str = "text",
        tema: str = "unknown",
    ) -> str:
        """Generates content and tracks usage. Returns the generated string."""


class OpenAIContentGenerator(ContentGenerator):
    def __init__(self) -> None:
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        # FIXED: was hardcoded "gpt-4o-mini" — now respects config
        self.model = settings.DEFAULT_MODEL

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        *,
        formato: str = "text",
        tema: str = "unknown",
    ) -> str:
        start_time = time.time()
        op_id = f"gen_openai_{start_time:.3f}"
        tracker.start_operation(op_id, "generation_openai")

        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
            )

            content = response.choices[0].message.content or ""
            usage = response.usage

            tracker.record_usage(
                op_id,
                usage.prompt_tokens,
                usage.completion_tokens,
                self.model,
                "generation_call",
            )

            latency = time.time() - start_time
            metrics = tracker.end_operation(op_id)
            cost = metrics.cost_usd if metrics else 0.0

            generation_logger.log_row(
                {
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
                }
            )

            return content

        except Exception:
            logger.exception("OpenAI generation failed")
            tracker.end_operation(op_id)  # always clean up
            raise


class GeminiContentGenerator(ContentGenerator):
    def __init__(self) -> None:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        # FIXED: was hardcoded "gemini-1.5-flash" — now respects config
        self.model_name = settings.DEFAULT_MODEL

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        *,
        formato: str = "text",
        tema: str = "unknown",
    ) -> str:
        start_time = time.time()
        op_id = f"gen_gemini_{start_time:.3f}"
        tracker.start_operation(op_id, "generation_gemini")

        try:
            # FIXED: use system_instruction param instead of string concat
            model = genai.GenerativeModel(
                self.model_name,
                system_instruction=system_prompt or None,
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

            generation_logger.log_row(
                {
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
                }
            )

            return content

        except Exception:
            logger.exception("Gemini generation failed")
            tracker.end_operation(op_id)  # always clean up
            raise

def get_content_generator() -> ContentGenerator:
    """Returns the appropriate ContentGenerator for the configured provider."""
    if settings.LLM_PROVIDER.lower() == "gemini":
        return GeminiContentGenerator()
    return OpenAIContentGenerator()