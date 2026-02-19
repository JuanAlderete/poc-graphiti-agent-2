import inspect
from graphiti_core.llm_client.client import LLMClient

try:
    sig = inspect.signature(LLMClient._generate_response)
    print(f"_generate_response signature: {sig}")
except Exception as e:
    print(f"Error: {e}")
