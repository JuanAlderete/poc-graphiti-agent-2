
try:
    from graphiti_core.llm_client.openai_client import OpenAIClient
    from graphiti_core.llm_client.config import LLMConfig
    
    print("Imports successful")
    
    config = LLMConfig(model="gpt-4o-mini", api_key="test_key")
    client = OpenAIClient(config=config)
    
    print("Client instantiated successfully")
    # To check model, we likely need to check client.config.model or similar
    # Based on init: self.config = config
    if client.config.model == "gpt-4o-mini":
        print(f"Verified model: {client.config.model}")
    else:
        print(f"Model mismatch ?? {client.config.model}")

except Exception as e:
    print(f"Failed: {e}")
