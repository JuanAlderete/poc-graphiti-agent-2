import asyncio
import json
import logging
import random
import re
import time
from typing import Any, Optional

from openai import AsyncOpenAI, RateLimitError, APIError
from openai.types.chat import ChatCompletion

from poc.config import config

logger = logging.getLogger(__name__)


class LLMResponse:
    """Respuesta normalizada del LLM."""
    def __init__(self, content: str, prompt_tokens: int, completion_tokens: int):
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


class OptimizedOpenAIClient:
    """
    Cliente LLM que soporta OpenAI y Ollama de forma transparente.

    Para Ollama: sin retry, sin budget guard, JSON parsing tolerante.
    Para OpenAI: exponential backoff, semáforo de concurrencia, budget guard.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        temperature: float = 0.1,
    ):
        self.provider = config.LLM_PROVIDER.lower()
        self.model = model or config.DEFAULT_MODEL
        self.max_retries = 1 if config.is_local else max_retries  # Ollama: sin retry
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.temperature = temperature
        self._semaphore: Optional[asyncio.Semaphore] = None

        # Construir cliente AsyncOpenAI — funciona para ambos providers
        client_kwargs: dict[str, Any] = {
            "api_key": config.OPENAI_API_KEY,
            "timeout": 120.0 if config.is_local else 60.0,  # Ollama es más lento
            "max_retries": 0,  # Manejamos retry nosotros
        }
        if config.OPENAI_BASE_URL:
            client_kwargs["base_url"] = config.OPENAI_BASE_URL

        self._client = AsyncOpenAI(**client_kwargs)

        logger.info(
            "OptimizedOpenAIClient inicializado: provider=%s, model=%s, base_url=%s",
            self.provider,
            self.model,
            config.OPENAI_BASE_URL or "https://api.openai.com/v1",
        )

    @property
    def semaphore(self) -> asyncio.Semaphore:
        """Lazy init del semáforo para evitar problemas con event loops."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_GENERATIONS)
        return self._semaphore

    async def complete(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict] = None,
    ) -> tuple[str, LLMResponse]:
        """
        Genera una completion y retorna (content, LLMResponse).

        Para Ollama: el response_format={"type": "json_object"} se traduce
        a instrucciones en el prompt (modelos pequeños lo ignoran a veces).
        """
        use_model = model or self.model
        use_temp = temperature if temperature is not None else self.temperature

        messages = [{"role": "user", "content": prompt}]

        # En Ollama: agregar instrucción JSON al prompt si se pide json_object
        if config.is_local and response_format == {"type": "json_object"}:
            messages = [{
                "role": "user",
                "content": prompt + "\n\nRespóndé ÚNICAMENTE con JSON válido, sin texto antes ni después, sin markdown."
            }]
            response_format = None  # Ollama puede no soportarlo

        return await self._make_request_with_retry(
            messages=messages,
            model=use_model,
            temperature=use_temp,
            max_tokens=max_tokens,
            response_format=response_format,
        )

    async def complete_with_system(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        response_format: Optional[dict] = None,
    ) -> tuple[str, LLMResponse]:
        """Completion con system prompt separado."""
        use_model = model or self.model
        use_temp = temperature if temperature is not None else self.temperature

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        if config.is_local and response_format == {"type": "json_object"}:
            messages[-1]["content"] += "\n\nRespóndé ÚNICAMENTE con JSON válido."
            response_format = None

        return await self._make_request_with_retry(
            messages=messages,
            model=use_model,
            temperature=use_temp,
            response_format=response_format,
        )

    async def _make_request_with_retry(
        self,
        messages: list,
        model: str,
        temperature: float,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict] = None,
    ) -> tuple[str, LLMResponse]:
        """
        Ejecuta la request con exponential backoff para OpenAI.
        Para Ollama: sin retry, timeout más largo.
        """
        async with self.semaphore:
            for attempt in range(self.max_retries):
                try:
                    kwargs: dict[str, Any] = {
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                    }
                    if max_tokens:
                        kwargs["max_tokens"] = max_tokens
                    if response_format:
                        kwargs["response_format"] = response_format

                    response: ChatCompletion = await self._client.chat.completions.create(**kwargs)

                    content = response.choices[0].message.content or ""
                    llm_response = LLMResponse(
                        content=content,
                        prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                        completion_tokens=response.usage.completion_tokens if response.usage else 0,
                    )
                    return content, llm_response

                except RateLimitError as e:
                    if config.is_local:
                        # Ollama no debería tener rate limits
                        logger.warning("Rate limit en Ollama (inesperado): %s", e)
                        raise

                    retry_after = self._extract_retry_after(e)
                    delay = self._calculate_delay(attempt, retry_after)
                    logger.warning(
                        "Rate limit en intento %d/%d. Esperando %.1fs...",
                        attempt + 1, self.max_retries, delay
                    )
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(delay)
                    else:
                        raise

                except APIError as e:
                    if attempt < self.max_retries - 1 and not config.is_local:
                        delay = self._calculate_delay(attempt)
                        logger.warning("API error en intento %d: %s. Retry en %.1fs", attempt + 1, e, delay)
                        await asyncio.sleep(delay)
                    else:
                        raise

                except Exception as e:
                    logger.error("Error inesperado en completions: %s", e)
                    raise

        raise RuntimeError("Max retries alcanzado sin respuesta exitosa")

    def parse_json_response(self, content: str) -> dict:
        """
        Parsea la respuesta JSON del LLM de forma tolerante.

        Modelos locales (Ollama con llama3.2) a veces envuelven el JSON
        en markdown o agregan texto antes/después. Este método lo maneja.
        """
        if not content:
            return {}

        # Intento 1: JSON directo
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Intento 2: extraer JSON de bloque markdown ```json ... ```
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Intento 3: buscar el primer { ... } en el texto
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning("No se pudo parsear JSON de la respuesta: %s", content[:200])
        return {}

    def _calculate_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after:
            base = retry_after
        else:
            base = self.base_delay * (2 ** attempt)
        jitter = base * 0.25 * (2 * random.random() - 1)
        return min(max(base + jitter, 0.1), self.max_delay)

    def _extract_retry_after(self, error: RateLimitError) -> Optional[float]:
        try:
            if hasattr(error, "response") and error.response:
                retry_after = error.response.headers.get("retry-after")
                if retry_after:
                    return float(retry_after)
        except Exception:
            pass
        return None

    async def close(self):
        await self._client.close()


# Alias para compatibilidad con código legacy
CustomOpenAIClient = OptimizedOpenAIClient