import asyncio
import logging
from functools import lru_cache
from typing import List, Tuple

import warnings
import google.generativeai as genai

# Suppress the deprecation warning
warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")
from openai import AsyncOpenAI

from agent.config import settings
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """
    Generates embeddings using the configured provider (OpenAI or Gemini).
    Instantiate once and reuse — see `get_embedder()` below.
    """

    def __init__(self) -> None:
        self.provider = settings.LLM_PROVIDER.lower()
        self.model = settings.EMBEDDING_MODEL

        if self.provider == "openai":
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        elif self.provider == "gemini":
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.client = None  # Gemini uses module-level calls
        else:
            logger.warning("Unknown provider '%s', defaulting to OpenAI", self.provider)
            self.provider = "openai"
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    # ------------------------------------------------------------------
    # Single-text embedding
    # ------------------------------------------------------------------

    async def generate_embedding(self, text: str) -> Tuple[List[float], int]:
        """
        Generates an embedding vector for *text*.
        Returns: (embedding_vector, token_count)
        """
        text = text.replace("\n", " ").strip()

        if self.provider == "gemini":
            return await self._embed_gemini_single(text)

        # OpenAI (async-native)
        try:
            response = await self.client.embeddings.create(input=[text], model=self.model)
            embedding = response.data[0].embedding
            tokens = response.usage.total_tokens
            return embedding, tokens
        except Exception:
            logger.exception("OpenAI embedding error for single text")
            raise

    # ------------------------------------------------------------------
    # Batch embedding
    # ------------------------------------------------------------------

    async def generate_embeddings_batch(self, texts: List[str]) -> Tuple[List[List[float]], int]:
        """
        Batch embedding generation.
        Returns: (list_of_embedding_vectors, total_token_count)
        """
        texts = [t.replace("\n", " ").strip() for t in texts]

        if self.provider == "gemini":
            return await self._embed_gemini_batch(texts)

        # OpenAI — single batched API call (most cost-effective)
        try:
            response = await self.client.embeddings.create(input=texts, model=self.model)
            # API guarantees same order as input
            embeddings = [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
            tokens = response.usage.total_tokens
            return embeddings, tokens
        except Exception:
            logger.exception("OpenAI batch embedding error")
            raise

    # ------------------------------------------------------------------
    # Gemini helpers (sync SDK wrapped in to_thread)
    # ------------------------------------------------------------------

    async def _embed_gemini_single(self, text: str) -> Tuple[List[float], int]:
        def _call():
            return genai.embed_content(
                model=f"models/{self.model}",
                content=text,
                task_type="retrieval_document",
            )

        try:
            result = await asyncio.to_thread(_call)
            embedding = result["embedding"]
            tokens = tracker.estimate_tokens(text)
            return embedding, tokens
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
            # Gemini returns {"embedding": [vec1, vec2, ...]} for list input
            raw = result["embedding"]
            # Normalise: ensure we always get List[List[float]]
            if raw and isinstance(raw[0], float):
                # Single-item batch returned a flat list
                embeddings = [raw]
            else:
                embeddings = raw
            tokens = sum(tracker.estimate_tokens(t) for t in texts)
            return embeddings, tokens
        except Exception:
            logger.exception("Gemini batch embedding error")
            raise


# ------------------------------------------------------------------
# Module-level singleton — avoids re-instantiating AsyncOpenAI on every call
# ------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_embedder() -> EmbeddingGenerator:
    """Returns the shared EmbeddingGenerator instance (created once per process)."""
    return EmbeddingGenerator()