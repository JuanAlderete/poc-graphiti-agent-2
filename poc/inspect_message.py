import inspect
try:
    from graphiti_core.prompts import Message
    print("Message class attributes:")
    print(inspect.signature(Message.__init__))
    # print instance attributes if possible
    m = Message(role="user", content="hello")
    print(f"Role: {m.role}, Content: {m.content}")
except ImportError:
    print("Could not import graphiti_core.prompts.Message")
except Exception as e:
    print(f"Error: {e}")
