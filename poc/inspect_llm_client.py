import inspect
from graphiti_core.llm_client.client import LLMClient
from graphiti_core.llm_client.openai_client import OpenAIClient 

print("LLMClient methods:")
for name, member in inspect.getmembers(LLMClient):
    if not name.startswith("__"):
        print(f"{name}: {member}")

print("\nOpenAIClient methods:")
for name, member in inspect.getmembers(OpenAIClient):
    if not name.startswith("__"):
        print(f"{name}: {member}")
