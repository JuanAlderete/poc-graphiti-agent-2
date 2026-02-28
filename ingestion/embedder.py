import asyncio
import logging
from typing import Dict, List, Optional, Tuple

from openai import AsyncOpenAI, RateLimitError

from poc.config import config
from poc.token_tracker import tracker

logger = logging.getLogger(__name__)

_CACHE_MAX = 256
_embedder_instance: Optional["EmbeddingGenerator"] = None


def get_embedder() -> "EmbeddingGenerator":
    """Retorna el singleton del EmbeddingGenerator. Thread-safe para asyncio."""
    global _embedder_instance
    if _embedder_instance is None:
        _embedder_instance = EmbeddingGenerator()
    return _embedder_instance


class EmbeddingGenerator:
    """
    Genera embeddings usando el proveedor configurado en LLM_PROVIDER.

    Para OpenAI y Ollama usa el mismo cliente AsyncOpenAI con distinta base_url.
    Para Gemini usa la librería google-generativeai.
    """

    def __init__(self):
        self.provider = config.LLM_PROVIDER.lower()
        self.model = config.EMBEDDING_MODEL
        self.dims = config.EMBEDDING_DIMS
        self._cache: Dict[str, List[float]] = {}

        logger.info(
            "EmbeddingGenerator: provider=%s, model=%s, dims=%d",
            self.provider, self.model, self.dims
        )

        if self.provider in ("openai", "ollama"):
            client_kwargs = {
                "api_key": config.OPENAI_API_KEY,
                "timeout": 60.0,
            }
            if config.OPENAI_BASE_URL:
                client_kwargs["base_url"] = config.OPENAI_BASE_URL
            self.client = AsyncOpenAI(**client_kwargs)
            self._embed_fn = self._embed_openai_compatible

        elif self.provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=config.GEMINI_API_KEY)
            self.client = None
            self._embed_fn = self._embed_gemini

        else:
            raise ValueError(f"Provider desconocido: {self.provider}")

    async def generate_embedding(self, text: str) -> Tuple[List[float], int]:
        """
        Embedding para un texto individual. Usa cache para queries repetidas.
        Retorna (vector, token_count_estimado).
        """
        clean = text.replace("\n", " ").strip()
        if not clean:
            return [0.0] * self.dims, 0

        if clean in self._cache:
            return self._cache[clean], tracker.estimate_tokens(clean)

        embedding, tokens = await self._embed_fn([clean])
        vector = embedding[0]

        # Eviction FIFO simple
        if len(self._cache) >= _CACHE_MAX:
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[clean] = vector

        return vector, tokens

    async def generate_embeddings_batch(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], int]:
        """
        Embedding para múltiples textos en una sola llamada (más eficiente).
        Retorna (lista_de_vectores, total_tokens).
        """
        cleaned = [t.replace("\n", " ").strip() for t in texts]

        # Separar los que ya están en cache
        to_embed_indices = []
        cached_results: Dict[int, List[float]] = {}

        for i, text in enumerate(cleaned):
            if text in self._cache:
                cached_results[i] = self._cache[text]
            else:
                to_embed_indices.append(i)

        total_tokens = 0
        if to_embed_indices:
            texts_to_embed = [cleaned[i] for i in to_embed_indices]
            new_embeddings, tokens = await self._embed_fn(texts_to_embed)
            total_tokens = tokens

            for idx, embedding in zip(to_embed_indices, new_embeddings):
                if len(self._cache) >= _CACHE_MAX:
                    oldest = next(iter(self._cache))
                    del self._cache[oldest]
                self._cache[cleaned[idx]] = embedding
                cached_results[idx] = embedding

        # Reconstruir en orden original
        result = [cached_results[i] for i in range(len(cleaned))]
        return result, total_tokens

    # =========================================================================
    # IMPLEMENTACIONES POR PROVEEDOR
    # =========================================================================

    async def _embed_openai_compatible(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], int]:
        """
        Embedding via API compatible con OpenAI.
        Funciona para OpenAI (api.openai.com) y Ollama (localhost:11434/v1).
        """
        try:
            response = await self.client.embeddings.create(
                input=texts,
                model=self.model,
            )
            embeddings = [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
            tokens = response.usage.total_tokens if response.usage else sum(
                tracker.estimate_tokens(t) for t in texts
            )

            # Validar dimensiones (solo en el primer batch)
            if embeddings and len(embeddings[0]) != self.dims:
                actual_dims = len(embeddings[0])
                logger.warning(
                    "DIMENSIÓN MISMATCH: config.EMBEDDING_DIMS=%d pero el modelo retornó %d dims. "
                    "Actualizá EMBEDDING_DIMS en .env o ejecutá scripts/reset_db.sh",
                    self.dims, actual_dims
                )
                # Actualizar dims para que el resto de la sesión funcione
                self.dims = actual_dims

            return embeddings, tokens

        except RateLimitError as e:
            if getattr(e, "code", None) == "insufficient_quota":
                logger.critical(
                    "FATAL: Quota de OpenAI agotada. "
                    "Para testing local, cambiá LLM_PROVIDER=ollama en .env"
                )
            raise

        except Exception as e:
            if config.is_local:
                logger.error(
                    "Error en Ollama embeddings: %s. "
                    "¿Está Ollama corriendo? ¿Está el modelo '%s' descargado? "
                    "Ejecutá: ollama pull %s",
                    e, self.model, self.model
                )
            raise

    async def _embed_gemini(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], int]:
        """Embedding via Google Gemini."""
        import google.generativeai as genai

        async def _embed_one(text: str) -> List[float]:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: genai.embed_content(
                    model=f"models/{self.model}",
                    content=text,
                    task_type="retrieval_document",
                )
            )
            return result["embedding"]

        embeddings = await asyncio.gather(*[_embed_one(t) for t in texts])
        total_tokens = sum(tracker.estimate_tokens(t) for t in texts)
        return list(embeddings), total_tokens