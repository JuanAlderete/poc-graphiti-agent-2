import asyncio
import logging
from functools import lru_cache
from typing import Dict, List, Tuple

import google.generativeai as genai
from openai import AsyncOpenAI

from agent.config import settings
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)

_CACHE_MAX = 256


class EmbeddingGenerator:
    def __init__(self):
        self.provider = settings.LLM_PROVIDER.lower()
        self.model = settings.EMBEDDING_MODEL
        self._cache: Dict[str, List[float]] = {}

        if self.provider == "openai":
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        elif self.provider == "gemini":
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.client = None
        else:
            logger.warning("Provider desconocido '%s', usando OpenAI.", self.provider)
            self.provider = "openai"
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def generate_embedding(self, text: str) -> Tuple[List[float], int]:
        """
        Embedding para un texto. Usa cache para queries repetidas.
        Retorna (vector, token_count).
        """
        clean = text.replace("\n", " ").strip()

        if clean in self._cache:
            return self._cache[clean], tracker.estimate_tokens(clean)

        embedding, tokens = await self._embed_one(clean)

        # Eviction FIFO si el cache está lleno
        if len(self._cache) >= _CACHE_MAX:
            del self._cache[next(iter(self._cache))]
        self._cache[clean] = embedding

        return embedding, tokens

    async def generate_embeddings_batch(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], int]:
        """Batch embedding. Retorna (lista_de_vectores, total_tokens)."""
        texts = [t.replace("\n", " ").strip() for t in texts]

        if self.provider == "gemini":
            return await self._embed_gemini_batch(texts)

        try:
            response = await self.client.embeddings.create(input=texts, model=self.model)
            embeddings = [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
            return embeddings, response.usage.total_tokens
        except Exception:
            logger.exception("Error en batch embedding OpenAI")
            raise

    async def _embed_one(self, text: str) -> Tuple[List[float], int]:
        if self.provider == "gemini":
            return await self._embed_gemini_single(text)
        try:
            response = await self.client.embeddings.create(input=[text], model=self.model)
            return response.data[0].embedding, response.usage.total_tokens
        except Exception:
            logger.exception("Error en embedding OpenAI")
            raise

    async def _embed_gemini_single(self, text: str) -> Tuple[List[float], int]:
        def _call():
            return genai.embed_content(
                model=f"models/{self.model}",
                content=text,
                task_type="retrieval_document",
            )
        result = await asyncio.to_thread(_call)
        return result["embedding"], tracker.estimate_tokens(text)

    async def _embed_gemini_batch(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], int]:
        def _call():
            return genai.embed_content(
                model=f"models/{self.model}",
                content=texts,
                task_type="retrieval_document",
            )
        result = await asyncio.to_thread(_call)
        raw = result["embedding"]
        embeddings = [raw] if raw and isinstance(raw[0], float) else raw
        return embeddings, sum(tracker.estimate_tokens(t) for t in texts)


@lru_cache(maxsize=1)
def get_embedder() -> EmbeddingGenerator:
    """Singleton compartido. Preserva el cache entre llamadas."""
    return EmbeddingGenerator()