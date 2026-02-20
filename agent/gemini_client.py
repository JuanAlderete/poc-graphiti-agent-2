import json
import logging
from typing import Any, Dict, List, Optional, Type

import warnings

# Suppress the "support has ended" warning from google.generativeai BEFORE import
warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")

import google.generativeai as genai

from agent.config import settings
from graphiti_core.llm_client.client import LLMClient
from graphiti_core.prompts import Message

logger = logging.getLogger(__name__)


class GeminiClient(LLMClient):
    """
    Implementación de LLMClient de graphiti-core usando Google Gemini.

    Soporta tanto respuestas de texto libre como respuestas estructuradas
    (cuando graphiti-core pasa `response_model` para extracción de entidades).
    """

    def __init__(self, model_name: str = "gemini-1.5-flash") -> None:
        self.api_key = settings.GEMINI_API_KEY
        genai.configure(api_key=self.api_key)
        self.model_name = model_name
        self._base_model = genai.GenerativeModel(model_name)
        # Cache de modelos por system_instruction para evitar re-instanciarlos
        self._model_cache: Dict[Optional[str], genai.GenerativeModel] = {
            None: self._base_model
        }

    def _get_model(self, system_instruction: Optional[str]) -> genai.GenerativeModel:
        """Retorna (cacheado) el modelo con la system_instruction dada."""
        if system_instruction not in self._model_cache:
            self._model_cache[system_instruction] = genai.GenerativeModel(
                self.model_name,
                system_instruction=system_instruction,
            )
        return self._model_cache[system_instruction]

    async def _generate_response(
        self,
        messages: List[Message],
        response_model: Optional[Type[BaseModel]] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Genera una respuesta de Gemini.

        Si `response_model` está presente (Pydantic), se pide JSON estructurado
        y se valida contra el schema del modelo. Esto es lo que graphiti-core
        usa para extraer entidades y relaciones del texto.
        """
        # ── Separar system prompt de los mensajes de usuario ─────────────────
        system_instruction: Optional[str] = None
        gemini_messages: List[Dict] = []

        for msg in messages:
            if msg.role == "system":
                system_instruction = (
                    system_instruction + "\n" + msg.content
                    if system_instruction
                    else msg.content
                )
            elif msg.role == "assistant":
                gemini_messages.append({"role": "model", "parts": [msg.content]})
            else:
                gemini_messages.append({"role": "user", "parts": [msg.content]})

        # Si se requiere respuesta estructurada, agregar instrucción al system prompt
        if response_model is not None:
            schema_json = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
            json_instruction = (
                f"\n\nIMPORTANT: You MUST respond with ONLY valid JSON that matches "
                f"this exact schema. Do not include any markdown, code blocks, or "
                f"explanation — only the raw JSON object:\n{schema_json}"
            )
            system_instruction = (system_instruction or "") + json_instruction

        # ── Llamada a Gemini ──────────────────────────────────────────────────
        model = self._get_model(system_instruction)

        try:
            response = await model.generate_content_async(
                gemini_messages,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.0 if response_model else 0.7,
                ),
            )
        except Exception as e:
            logger.error("Gemini generate_content_async failed: %s", e)
            raise

        # ── Validar que hay contenido en la respuesta ────────────────────────
        if not response.candidates:
            block_reason = getattr(response.prompt_feedback, "block_reason", "unknown")
            logger.error(
                "Gemini returned no candidates. Block reason: %s", block_reason
            )
            raise ValueError(f"Gemini blocked the response: {block_reason}")

        try:
            text_content = response.text
        except ValueError as e:
            # response.text lanza ValueError si el candidato fue bloqueado por safety
            logger.error("Gemini response blocked by safety filter: %s", e)
            raise

        if not text_content:
            raise ValueError("Gemini returned empty text content")

        # ── Si se esperaba JSON estructurado, parsear y validar ──────────────
        if response_model is not None:
            # Limpiar posibles backticks de markdown que Gemini a veces agrega
            clean_text = text_content.strip()
            if clean_text.startswith("```"):
                clean_text = clean_text.split("\n", 1)[-1]
                clean_text = clean_text.rsplit("```", 1)[0]
            clean_text = clean_text.strip()

            try:
                parsed = response_model.model_validate_json(clean_text)
                # Retornar el objeto parseado como dict para que graphiti-core lo use
                return {
                    "content": clean_text,
                    "parsed": parsed,
                    "usage": self._extract_usage(response),
                    "tool_calls": [],
                }
            except Exception as e:
                logger.warning(
                    "Failed to parse Gemini response as %s: %s\nRaw: %s",
                    response_model.__name__,
                    e,
                    clean_text[:500],
                )
                # Retornar el texto crudo y dejar que graphiti-core lo intente parsear
                return {
                    "content": clean_text,
                    "usage": self._extract_usage(response),
                    "tool_calls": [],
                }

        # ── Respuesta de texto libre ──────────────────────────────────────────
        return {
            "content": text_content,
            "usage": self._extract_usage(response),
            "tool_calls": [],
        }

    def _extract_usage(self, response: Any) -> Dict[str, int]:
        """Extrae métricas de uso de tokens de la respuesta de Gemini."""
        if response.usage_metadata:
            return {
                "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
                "completion_tokens": response.usage_metadata.candidates_token_count or 0,
                "total_tokens": response.usage_metadata.total_token_count or 0,
            }
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}