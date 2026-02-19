import inspect
import pkgutil
import importlib

def list_classes(module_name):
    try:
        module = importlib.import_module(module_name)
        print(f"\nClasses in {module_name}:")
        for name, obj in inspect.getmembers(module, inspect.isclass):
            print(f"  {name}")
            
        # Also try to walk packages if it's a package
        if hasattr(module, "__path__"):
             for importer, modname, ispkg in pkgutil.walk_packages(module.__path__, module_name + "."):
                try:
                    submod = importlib.import_module(modname)
                    for name, obj in inspect.getmembers(submod, inspect.isclass):
                        print(f"  {modname}.{name}")
                except Exception:
                    pass

    except Exception as e:
        print(f"Error inspecting {module_name}: {e}")

list_classes("graphiti_core.llm_client")
list_classes("graphiti_core.embedder")
