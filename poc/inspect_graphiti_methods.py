import inspect
try:
    from graphiti_core import Graphiti
    print("Graphiti methods:")
    for name, member in inspect.getmembers(Graphiti):
        if not name.startswith("__") and inspect.isfunction(member):
            print(name)
except ImportError:
    print("Could not import graphiti_core")
except Exception as e:
    print(f"Error: {e}")
