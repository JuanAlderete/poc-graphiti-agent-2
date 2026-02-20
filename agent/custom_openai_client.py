import asyncio
import logging
import typing

import openai
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.errors import RateLimitError, RefusalError
from graphiti_core.llm_client.openai_client import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_SMALL_MODEL,
    ModelSize,
    OpenAIClient,
)
from graphiti_core.prompts.models import Message

logger = logging.getLogger(__name__)

_MAX_RATE_LIMIT_RETRIES = 5
_RETRY_BASE_SECONDS = 10

# FIX BUG 2 (iteracion 3): 16384 para cubrir reasoning + JSON output.
# Los prompts de graphiti-core llegan a ~20k tokens.
# El reasoning consume 8000-12000 tokens en esos casos.
# El JSON de output necesita ~300-500 tokens adicionales.
# Total worst-case: ~12500 -> 16384 da margen seguro.
_MAX_TOKENS_REASONING_MODELS = 16384


class CustomOpenAIClient(OpenAIClient):
    """
    Subclass de OpenAIClient para modelos gpt-5-* y o1-*.

    1. max_completion_tokens=16384 para cubrir reasoning interno.
    2. small_model = medium_model (evita gpt-4.1-nano con limite 200k TPM).
    3. Retry con backoff ante 429.
    """

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)

        original_small = self.small_model or DEFAULT_SMALL_MODEL
        if self.model and self.model != original_small:
            logger.info(
                "CustomOpenAIClient: overriding small_model '%s' -> '%s'",
                original_small, self.model,
            )
            self.small_model = self.model

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, typing.Any]:

        if model_size == ModelSize.small:
            model = self.small_model or DEFAULT_SMALL_MODEL
        else:
            model = self.model or DEFAULT_MODEL

        openai_messages: list[ChatCompletionMessageParam] = []
        for m in messages:
            m.content = self._clean_input(m.content)
            if m.role == "user":
                openai_messages.append({"role": "user", "content": m.content})
            elif m.role == "system":
                openai_messages.append({"role": "system", "content": m.content})

        # gpt-5-* y o1-* son reasoning models:
        # - usan max_completion_tokens (no max_tokens)
        # - no aceptan temperature
        # - consumen reasoning_tokens antes de generar output visible
        is_reasoning_model = model.startswith("o1-") or model.startswith("gpt-5")

        if is_reasoning_model:
            effective_max_tokens = _MAX_TOKENS_REASONING_MODELS
        else:
            effective_max_tokens = max_tokens or self.max_tokens or DEFAULT_MAX_TOKENS

        kwargs: dict[str, typing.Any] = {
            "model": model,
            "messages": openai_messages,
            "response_format": response_model,
        }

        if not is_reasoning_model:
            kwargs["temperature"] = self.temperature

        if is_reasoning_model:
            kwargs["max_completion_tokens"] = effective_max_tokens
        else:
            kwargs["max_tokens"] = effective_max_tokens

        last_error: Exception | None = None
        for attempt in range(_MAX_RATE_LIMIT_RETRIES):
            try:
                response = await self.client.beta.chat.completions.parse(**kwargs)
                response_object = response.choices[0].message

                if response_object.parsed:
                    return response_object.parsed.model_dump()
                elif response_object.refusal:
                    raise RefusalError(response_object.refusal)
                else:
                    raise Exception(
                        f"Invalid response from LLM: {response_object.model_dump()}"
                    )

            except openai.LengthFinishReasonError as e:
                raise Exception(f"Output length exceeded: {e}") from e

            except openai.RateLimitError as e:
                last_error = e
                wait = _RETRY_BASE_SECONDS * (2 ** attempt)
                if attempt < _MAX_RATE_LIMIT_RETRIES - 1:
                    logger.warning(
                        "Rate limit on '%s' (attempt %d/%d). Waiting %ds...",
                        model, attempt + 1, _MAX_RATE_LIMIT_RETRIES, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        "Rate limit persists after %d attempts.", _MAX_RATE_LIMIT_RETRIES
                    )
                    raise RateLimitError from e

            except Exception as e:
                logger.error("LLM response error: %s", e)
                raise

        raise RateLimitError from last_error