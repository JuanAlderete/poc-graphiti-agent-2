from abc import ABC, abstractmethod
import logging
import google.generativeai as genai
from openai import AsyncOpenAI
from agent.config import settings
from poc.token_tracker import tracker
from poc.logging_utils import generation_logger
import time

logger = logging.getLogger(__name__)

class ContentGenerator(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generates content and tracks usage."""
        pass

class OpenAIContentGenerator(ContentGenerator):
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        # We might want to make the model configurable per call, but simpler here
        self.model = "gpt-4o-mini" # or from config

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        start_time = time.time()
        op_id = f"gen_openai_{int(start_time*1000)}"
        tracker.start_operation(op_id, "generation_openai")

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
            
            # Estimate input tokens logic is handled by API response usually, 
            # but we can pre-calculate if needed. 
            # For accurate costs, we use the usage from response.
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages
            )
            
            content = response.choices[0].message.content
            usage = response.usage
            
            tracker.record_usage(
                op_id, 
                usage.prompt_tokens, 
                usage.completion_tokens, 
                self.model, 
                "generation_call"
            )
            
            latency = time.time() - start_time
            metrics = tracker.end_operation(op_id)
            cost = metrics.cost_usd if metrics else 0.0

            generation_logger.log_row({
                "pieza_id": op_id,
                "timestamp": start_time,
                "formato": "text", # Placeholder
                "tema_base": "unknown", # Placeholder
                "tokens_contexto_in": 0, # Could split out system/context
                "tokens_prompt_in": usage.prompt_tokens,
                "tokens_out": usage.completion_tokens,
                "modelo": self.model,
                "provider": "openai",
                "costo_usd": cost,
                "tiempo_seg": latency,
                "longitud_output_chars": len(content)
            })
            
            return content

        except Exception as e:
            logger.error(f"OpenAI Generation failed: {e}")
            tracker.end_operation(op_id)
            raise

class GeminiContentGenerator(ContentGenerator):
    def __init__(self):
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model_name = "gemini-1.5-flash" # Default
        self.model = genai.GenerativeModel(self.model_name)

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        start_time = time.time()
        op_id = f"gen_gemini_{int(start_time*1000)}"
        tracker.start_operation(op_id, "generation_gemini")
        
        try:
            # Gemini Python SDK doesn't always have exact system prompt support in same way
            # We construct a combined prompt or use system_instruction if supported
            full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            
            # Count tokens (async not available for count_tokens?)
            # create_content is async? 
            # The google-generativeai SDK is primarily synchronous for some calls, 
            # check async support. 
            # 'generate_content_async' exists in recent versions.
            
            response = await self.model.generate_content_async(full_prompt)
            content = response.text
            
            # Usage metadata
            # usage_metadata might be in response.usage_metadata
            usage = response.usage_metadata
            p_tokens = usage.prompt_token_count
            c_tokens = usage.candidates_token_count
            
            tracker.record_usage(
                op_id, 
                p_tokens, 
                c_tokens, 
                self.model_name, 
                "generation_call"
            )
            
            latency = time.time() - start_time
            metrics = tracker.end_operation(op_id)
            cost = metrics.cost_usd if metrics else 0.0
            
            generation_logger.log_row({
                "pieza_id": op_id,
                "timestamp": start_time,
                "formato": "text",
                "tema_base": "unknown",
                "tokens_prompt_in": p_tokens,
                "tokens_out": c_tokens,
                "modelo": self.model_name,
                "provider": "gemini",
                "costo_usd": cost,
                "tiempo_seg": latency,
                "longitud_output_chars": len(content)
            })
            
            return content

        except Exception as e:
            logger.error(f"Gemini Generation failed: {e}")
            tracker.end_operation(op_id)
            raise

def get_content_generator() -> ContentGenerator:
    provider = settings.LLM_PROVIDER.lower()
    if provider == "gemini":
        return GeminiContentGenerator()
    else:
        return OpenAIContentGenerator()
