import inspect
from graphiti_core.llm_client.client import LLMClient

print("LLMClient methods:")
for name, member in inspect.getmembers(LLMClient):
    if not name.startswith("__"):
        if inspect.isfunction(member):
            try:
                sig = inspect.signature(member)
                print(f"Method: {name}{sig}")
            except ValueError:
                print(f"Method: {name} (no signature)")
