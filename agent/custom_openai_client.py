import typing
from pydantic import BaseModel
from openai.types.chat import ChatCompletionMessageParam
import openai
from graphiti_core.llm_client.openai_client import OpenAIClient, ModelSize, DEFAULT_MODEL, DEFAULT_SMALL_MODEL, DEFAULT_MAX_TOKENS
from graphiti_core.prompts.models import Message
from graphiti_core.llm_client.errors import RateLimitError, RefusalError
import logging

logger = logging.getLogger(__name__)

class CustomOpenAIClient(OpenAIClient):
    """
    Subclass of OpenAIClient to support models that require `max_completion_tokens`
    instead of `max_tokens` (e.g., o1-preview, o1-mini, gpt-5-mini).
    """

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, typing.Any]:
        openai_messages: list[ChatCompletionMessageParam] = []
        for m in messages:
            m.content = self._clean_input(m.content)
            if m.role == 'user':
                openai_messages.append({'role': 'user', 'content': m.content})
            elif m.role == 'system':
                openai_messages.append({'role': 'system', 'content': m.content})
        try:
            if model_size == ModelSize.small:
                model = self.small_model or DEFAULT_SMALL_MODEL
            else:
                model = self.model or DEFAULT_MODEL

            # --- CUSTOM LOGIC START ---
            # Check if using a model that likely requires max_completion_tokens
            # For this POC, we assume any model starting with 'o1-' or 'gpt-5' needs this.
            use_completion_tokens = model.startswith("o1-") or model.startswith("gpt-5")
            
            kwargs = {
                "model": model,
                "messages": openai_messages,
                # "temperature": self.temperature, # O-series models often don't support temp, but let's keep it unless it errors
                "response_format": response_model,
            }

            # Some models don't support temperature (e.g. o1-preview, gpt-5-mini)
            if not model.startswith("o1-") and not model.startswith("gpt-5"):
                 kwargs["temperature"] = self.temperature

            if use_completion_tokens:
                 # Rename parameter
                 kwargs["max_completion_tokens"] = max_tokens or self.max_tokens
            else:
                 kwargs["max_tokens"] = max_tokens or self.max_tokens
            
            # --- CUSTOM LOGIC END ---

            response = await self.client.beta.chat.completions.parse(**kwargs)

            response_object = response.choices[0].message

            if response_object.parsed:
                return response_object.parsed.model_dump()
            elif response_object.refusal:
                raise RefusalError(response_object.refusal)
            else:
                raise Exception(f'Invalid response from LLM: {response_object.model_dump()}')
        except openai.LengthFinishReasonError as e:
            raise Exception(f'Output length exceeded max tokens {self.max_tokens}: {e}') from e
        except openai.RateLimitError as e:
            raise RateLimitError from e
        except Exception as e:
            logger.error(f'Error in generating LLM response: {e}')
            raise
