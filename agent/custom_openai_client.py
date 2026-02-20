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

_MAX_RETRIES = 5
_RETRY_BASE_SECONDS = 10

# Para gpt-5-* y o1-*: reasoning consume ~8-12k tokens antes del output.
# Con prompt ~20k: reasoning ~8-12k + JSON output ~500 = ~12500 worst case.
# 16384 cubre con margen; tokens no usados no se cobran.
_MAX_TOKENS_REASONING = 16384


class CustomOpenAIClient(OpenAIClient):
    """
    Drop-in replacement para OpenAIClient de graphiti-core.

    Registrar en graph_utils.py:
        from agent.custom_openai_client import CustomOpenAIClient
        llm_client = CustomOpenAIClient(config=LLMConfig(...))
    """

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        original = self.small_model or DEFAULT_SMALL_MODEL
        if self.model and self.model != original:
            logger.info(
                "CustomOpenAIClient: small_model '%s' -> '%s'",
                original, self.model,
            )
            self.small_model = self.model

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, typing.Any]:

        model = (
            self.small_model or DEFAULT_SMALL_MODEL
            if model_size == ModelSize.small
            else self.model or DEFAULT_MODEL
        )

        openai_messages: list[ChatCompletionMessageParam] = []
        for m in messages:
            m.content = self._clean_input(m.content)
            if m.role == "user":
                openai_messages.append({"role": "user", "content": m.content})
            elif m.role == "system":
                openai_messages.append({"role": "system", "content": m.content})

        is_reasoning = model.startswith("o1-") or model.startswith("gpt-5")

        effective_tokens = (
            _MAX_TOKENS_REASONING if is_reasoning
            else (max_tokens or self.max_tokens or DEFAULT_MAX_TOKENS)
        )

        kwargs: dict[str, typing.Any] = {
            "model": model,
            "messages": openai_messages,
            "response_format": response_model,
        }
        if not is_reasoning:
            kwargs["temperature"] = self.temperature
        if is_reasoning:
            kwargs["max_completion_tokens"] = effective_tokens
        else:
            kwargs["max_tokens"] = effective_tokens

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self.client.beta.chat.completions.parse(**kwargs)
                msg = response.choices[0].message
                if msg.parsed:
                    return msg.parsed.model_dump()
                if msg.refusal:
                    raise RefusalError(msg.refusal)
                raise Exception(f"Unexpected LLM response: {msg.model_dump()}")

            except openai.LengthFinishReasonError as e:
                raise Exception(f"Output length exceeded: {e}") from e

            except openai.RateLimitError as e:
                last_exc = e
                wait = _RETRY_BASE_SECONDS * (2 ** attempt)
                if attempt < _MAX_RETRIES - 1:
                    logger.warning(
                        "429 en '%s' (intento %d/%d). Esperando %ds...",
                        model, attempt + 1, _MAX_RETRIES, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("Rate limit persiste tras %d intentos.", _MAX_RETRIES)
                    raise RateLimitError from e

            except Exception as e:
                logger.error("Error LLM: %s", e)
                raise

        raise RateLimitError from last_exc