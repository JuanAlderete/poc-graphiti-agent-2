import asyncio
import logging
from functools import lru_cache
from typing import Dict, List, Tuple

import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")

import google.generativeai as genai
from openai import AsyncOpenAI

from agent.config import settings
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)

_MAX_QUERY_CACHE = 256


class EmbeddingGenerator:
    """
    Genera embeddings usando el proveedor configurado (OpenAI o Gemini).
    Instanciar una sola vez y reutilizar -- ver get_embedder().
    Incluye cache en memoria para queries repetidas.
    """

    def __init__(self) -> None:
        self.provider = settings.LLM_PROVIDER.lower()
        self.model = settings.EMBEDDING_MODEL
        self._query_cache: Dict[str, List[float]] = {}

        if self.provider == "openai":
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        elif self.provider == "gemini":
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.client = None
        else:
            logger.warning("Unknown provider '%s', defaulting to OpenAI", self.provider)
            self.provider = "openai"
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def generate_embedding(self, text: str) -> Tuple[List[float], int]:
        """
        Genera un vector de embedding para text.
        Usa cache si el texto ya fue procesado antes.
        Retorna: (embedding_vector, token_count)
        """
        clean = text.replace("\n", " ").strip()

        # Cache hit: 0 tokens, 0 latencia, $0 costo
        if clean in self._query_cache:
            logger.debug("Embedding cache hit (len=%d)", len(clean))
            return self._query_cache[clean], tracker.estimate_tokens(clean)

        embedding, tokens = await self._embed_single_uncached(clean)

        # Eviction FIFO si el cache esta lleno
        if len(self._query_cache) >= _MAX_QUERY_CACHE:
            oldest_key = next(iter(self._query_cache))
            del self._query_cache[oldest_key]
        self._query_cache[clean] = embedding

        return embedding, tokens

    async def generate_embeddings_batch(self, texts: List[str]) -> Tuple[List[List[float]], int]:
        """
        Genera embeddings en batch para una lista de textos.
        Retorna: (lista_de_vectores, total_tokens)
        """
        texts = [t.replace("\n", " ").strip() for t in texts]

        if self.provider == "gemini":
            return await self._embed_gemini_batch(texts)

        try:
            response = await self.client.embeddings.create(input=texts, model=self.model)
            embeddings = [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
            tokens = response.usage.total_tokens
            return embeddings, tokens
        except Exception:
            logger.exception("OpenAI batch embedding error")
            raise

    async def _embed_single_uncached(self, text: str) -> Tuple[List[float], int]:
        if self.provider == "gemini":
            return await self._embed_gemini_single(text)
        try:
            response = await self.client.embeddings.create(input=[text], model=self.model)
            return response.data[0].embedding, response.usage.total_tokens
        except Exception:
            logger.exception("OpenAI embedding error")
            raise

    async def _embed_gemini_single(self, text: str) -> Tuple[List[float], int]:
        def _call():
            return genai.embed_content(
                model=f"models/{self.model}",
                content=text,
                task_type="retrieval_document",
            )
        try:
            result = await asyncio.to_thread(_call)
            return result["embedding"], tracker.estimate_tokens(text)
        except Exception:
            logger.exception("Gemini single embedding error")
            raise

    async def _embed_gemini_batch(self, texts: List[str]) -> Tuple[List[List[float]], int]:
        def _call():
            return genai.embed_content(
                model=f"models/{self.model}",
                content=texts,
                task_type="retrieval_document",
            )
        try:
            result = await asyncio.to_thread(_call)
            raw = result["embedding"]
            embeddings = [raw] if raw and isinstance(raw[0], float) else raw
            return embeddings, sum(tracker.estimate_tokens(t) for t in texts)
        except Exception:
            logger.exception("Gemini batch embedding error")
            raise

    def cache_stats(self) -> dict:
        return {"cached_queries": len(self._query_cache), "max_capacity": _MAX_QUERY_CACHE}


@lru_cache(maxsize=1)
def get_embedder() -> EmbeddingGenerator:
    """Retorna la instancia compartida de EmbeddingGenerator."""
    return EmbeddingGenerator()