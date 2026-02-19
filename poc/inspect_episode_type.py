import inspect
try:
    from graphiti_core.nodes import EpisodeType
    print("EpisodeType members:")
    for name, member in EpisodeType.__members__.items():
        print(f"{name}: {member}")
except ImportError:
    print("Could not import EpisodeType")
except Exception as e:
    print(f"Error: {e}")
