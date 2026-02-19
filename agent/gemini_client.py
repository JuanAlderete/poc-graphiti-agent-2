import google.generativeai as genai
from typing import List, Dict, Any, Optional
from graphiti_core.llm_client.client import LLMClient
from graphiti_core.prompts import Message
from agent.config import settings
import logging

logger = logging.getLogger(__name__)

class GeminiClient(LLMClient):
    def __init__(self, model_name: str = "gemini-1.5-flash"):
        self.api_key = settings.GEMINI_API_KEY
        genai.configure(api_key=self.api_key)
        self.model_name = model_name
        self.model = genai.GenerativeModel(model_name)
        
    async def _generate_response(self, messages: List[Message], functions: Optional[List[Any]] = None, tools: Optional[List[Any]] = None, model_size: Any = None) -> Dict[str, Any]:
        """
        Internal method to generate response from Gemini.
        Signature matches LLMClient._generate_response.
        """
        try:
            system_instruction = None
            gemini_messages = []
            
            for msg in messages:
                role = msg.role
                content = msg.content
                
                if role == "system":
                    if system_instruction:
                        system_instruction += "\n" + content
                    else:
                        system_instruction = content
                elif role == "user":
                    gemini_messages.append({"role": "user", "parts": [content]})
                elif role == "assistant":
                    gemini_messages.append({"role": "model", "parts": [content]})
                else:
                    logger.warning(f"Unknown role {role}, treating as user")
                    gemini_messages.append({"role": "user", "parts": [content]})
            
            # Re-initialize model with system instruction if present
            if system_instruction:
                model = genai.GenerativeModel(self.model_name, system_instruction=system_instruction)
            else:
                model = self.model
                
            response = await model.generate_content_async(gemini_messages)
            
            # Helper to get usage if available
            usage = {}
            if response.usage_metadata:
                usage = {
                    "prompt_tokens": response.usage_metadata.prompt_token_count,
                    "completion_tokens": response.usage_metadata.candidates_token_count,
                    "total_tokens": response.usage_metadata.total_token_count
                }

            # LLMClient expects a dict return. 
            # Looking at how OpenAIClient likely works, it probably returns:
            # { "content": <text>, "usage": <usage_dict>, "tool_calls": ... }
            return {
                "content": response.text,
                "usage": usage,
                "tool_calls": [] # Not implementing tools yet
            }
            
        except Exception as e:
            logger.error(f"GeminiClient generation failed: {e}")
            raise

