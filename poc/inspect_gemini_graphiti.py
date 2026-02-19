import inspect
try:
    import graphiti_core.llm_client.gemini as gemini_llm
    print("Found graphiti_core.llm_client.gemini")
    for name, obj in inspect.getmembers(gemini_llm, inspect.isclass):
        print(f"Class: {name}")
        try:
            print(inspect.signature(obj.__init__))
        except:
            pass
except ImportError:
    print("Could not import graphiti_core.llm_client.gemini")

print("-" * 20)

try:
    import graphiti_core.embedder.gemini as gemini_embedder
    print("Found graphiti_core.embedder.gemini")
    for name, obj in inspect.getmembers(gemini_embedder, inspect.isclass):
        print(f"Class: {name}")
        try:
            print(inspect.signature(obj.__init__))
        except:
            pass
except ImportError:
    print("Could not import graphiti_core.embedder.gemini")
