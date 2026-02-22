import asyncio
import os
import time
import random
from typing import Optional
import logging

from openai import AsyncOpenAI, RateLimitError, APIError
from graphiti_core.llm_client.client import LLMClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.errors import RateLimitError as GraphitiRateLimitError

logger = logging.getLogger(__name__)

class OptimizedOpenAIClient(LLMClient):
    """
    Optimized OpenAI client with:
    - Exponential backoff for rate limiting
    - HTTP connection pooling
    - Token usage optimization
    - Request batching
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-5-mini",
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        temperature: float = 0.1,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found")
        
        self.model = model
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.temperature = temperature
        
        # Reutilizar el cliente HTTP con connection pooling
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            timeout=60.0,
            max_retries=0,  # Manejamos nosotros los retries
        )
        
        # Semáforo para limitar concurrencia
        self._semaphore = None  # Se inicializará en setup
        
        logger.info(f"Initialized OptimizedOpenAIClient with model: {model}")
    
    async def setup(self):
        """Initialize async resources."""
        self._semaphore = asyncio.Semaphore(3)  # Máximo 3 requests concurrentes
    
    async def close(self):
        """Cleanup resources."""
        await self._client.close()
    
    def _calculate_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """
        Calculate delay with exponential backoff and jitter.
        
        Formula: min(base_delay * 2^attempt + random_jitter, max_delay)
        """
        if retry_after:
            # Respetar el header Retry-After de OpenAI
            base = retry_after
        else:
            base = self.base_delay * (2 ** attempt)
        
        # Agregar jitter (±25%) para evitar thundering herd
        jitter = base * 0.25 * (2 * random.random() - 1)
        delay = min(base + jitter, self.max_delay)
        
        return max(delay, 0.1)  # Mínimo 100ms
    
    def _truncate_content(self, content: str, max_tokens: int = 4000) -> str:
        """
        Truncate content to stay within token limits.
        Aproximadamente 4 caracteres por token para inglés/español.
        """
        max_chars = max_tokens * 4
        
        if len(content) <= max_chars:
            return content
        
        # Truncar manteniendo el inicio y final (contexto más importante)
        half_limit = max_chars // 2
        truncated = content[:half_limit] + "\n\n[... contenido truncado por límite de tokens ...]\n\n" + content[-half_limit:]
        
        logger.warning(f"Content truncated from {len(content)} to {len(truncated)} chars")
        return truncated
    
    async def _make_request_with_retry(
        self,
        messages: list,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Make API request with exponential backoff retry logic.
        """
        temp = temperature if temperature is not None else self.temperature
        
        # Lazy-init semaphore if setup() was never called
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(3)
        
        for attempt in range(self.max_retries):
            try:
                # Limitar concurrencia con semáforo
                async with self._semaphore:
                    response = await self._client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=temp,
                        max_tokens=max_tokens,
                    )
                    
                    # Log de uso de tokens para monitoreo
                    usage = response.usage
                    if usage:
                        logger.info(
                            f"Tokens used - Prompt: {usage.prompt_tokens}, "
                            f"Completion: {usage.completion_tokens}, "
                            f"Total: {usage.total_tokens}"
                        )
                    
                    return response.choices[0].message.content
            
            except RateLimitError as e:
                # insufficient_quota = billing problem, not a transient rate limit.
                # Retrying is useless — stop immediately with a clear message.
                error_code = getattr(e, "code", None)
                if error_code == "insufficient_quota":
                    logger.critical(
                        "FATAL: OpenAI quota exceeded (insufficient_quota). "
                        "Please top up your account at https://platform.openai.com/account/billing"
                    )
                    raise

                retry_after = None

                # Extraer Retry-After del header si existe
                if hasattr(e, 'response') and e.response:
                    retry_after = e.response.headers.get('retry-after')
                    if retry_after:
                        retry_after = float(retry_after)

                delay = self._calculate_delay(attempt, retry_after)

                logger.warning(
                    f"Rate limit hit (attempt {attempt + 1}/{self.max_retries}). "
                    f"Retrying in {delay:.2f}s..."
                )

                await asyncio.sleep(delay)
            
            except APIError as e:
                # Errores transitorios de API (5xx, timeouts)
                if attempt < self.max_retries - 1:
                    delay = self._calculate_delay(attempt)
                    logger.warning(f"API error: {e}. Retrying in {delay:.2f}s...")
                    await asyncio.sleep(delay)
                else:
                    raise
            
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise
        
        # Si agotamos los retries
        raise GraphitiRateLimitError(f"Max retries ({self.max_retries}) exceeded")
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Generate text with token optimization and retry logic.
        """
        # Optimizar el contenido del prompt
        optimized_prompt = self._truncate_content(prompt, max_tokens=3500)
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": optimized_prompt})
        
        return await self._make_request_with_retry(
            messages=messages,
            temperature=temperature,
        )
    
    # Métodos requeridos por Graphiti
    async def generate_with_context(self, context: str, prompt: str) -> str:
        """Generate with context (used by Graphiti)."""
        combined = f"Context:\n{context}\n\nTask:\n{prompt}"
        return await self.generate(combined)
    
    async def generate_entity_summary(self, text: str) -> str:
        """Generate entity summary with token optimization."""
        optimized = self._truncate_content(text, max_tokens=2000)
        prompt = f"Summarize the key entities in this text:\n\n{optimized}"
        return await self.generate(prompt)
    
    async def generate_edge_summary(self, source: str, target: str, context: str) -> str:
        """Generate edge summary."""
        optimized_context = self._truncate_content(context, max_tokens=1500)
        prompt = f"Describe the relationship between '{source}' and '{target}':\n\n{optimized_context}"
        return await self.generate(prompt)