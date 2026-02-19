import inspect
try:
    from graphiti_core import Graphiti
    sig = inspect.signature(Graphiti.add_episode)
    print("Graphiti.add_episode signature:")
    for name, param in sig.parameters.items():
        print(f"{name}: {param.annotation} = {param.default}")
except ImportError:
    print("Could not import graphiti_core")
except Exception as e:
    print(f"Error: {e}")


