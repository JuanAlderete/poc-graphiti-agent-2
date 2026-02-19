import google.generativeai as genai
from openai import AsyncOpenAI
from typing import List, Tuple
from agent.config import settings
from poc.token_tracker import tracker
import logging

logger = logging.getLogger(__name__)

class EmbeddingGenerator:
    def __init__(self):
        self.provider = settings.LLM_PROVIDER.lower()
        self.model = settings.EMBEDDING_MODEL
        
        if self.provider == "openai":
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        elif self.provider == "gemini":
            genai.configure(api_key=settings.GEMINI_API_KEY)
        else:
            logger.warning(f"Unknown provider {self.provider}, defaulting to OpenAI behavior")
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def generate_embedding(self, text: str) -> Tuple[List[float], int]:
        """
        Generates embedding for a string.
        Returns: (embedding_vector, token_count)
        """
        try:
            text = text.replace("\n", " ")
            
            if self.provider == "gemini":
                # Gemini Embedding
                result = genai.embed_content(
                    model=f"models/{self.model}",
                    content=text,
                    task_type="retrieval_document"
                )
                embedding = result['embedding']
                # Token count approximation or API field if available (Gemini embed doesn't always return usage)
                # We'll approximate or check if result has it. 
                # For now, simplistic char count / 4
                tokens = len(text) // 4 
                return embedding, tokens
            else:
                # OpenAI Embedding
                response = await self.client.embeddings.create(
                    input=[text],
                    model=self.model
                )
                embedding = response.data[0].embedding
                tokens = response.usage.total_tokens
                return embedding, tokens
            
        except Exception as e:
            logger.error(f"Error generating embedding ({self.provider}): {e}")
            raise

    async def generate_embeddings_batch(self, texts: List[str]) -> Tuple[List[List[float]], int]:
        """Batch embedding generation."""
        try:
            texts = [t.replace("\n", " ") for t in texts]
            
            if self.provider == "gemini":
                # Batch not always purely supported by simple call, loop or batch method
                # embed_content supports list of content? Yes.
                result = genai.embed_content(
                    model=f"models/{self.model}",
                    content=texts,
                    task_type="retrieval_document"
                )
                embeddings = result['embedding']
                tokens = sum(len(t) for t in texts) // 4
                return embeddings, tokens
                
            else:
                response = await self.client.embeddings.create(
                    input=texts,
                    model=self.model
                )
                embeddings = [d.embedding for d in response.data]
                tokens = response.usage.total_tokens
                return embeddings, tokens
            
        except Exception as e:
            logger.error(f"Error generating embeddings batch ({self.provider}): {e}")
            raise

