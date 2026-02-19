import asyncio
import logging
from agent.gemini_client import GeminiClient
from graphiti_core.prompts import Message

# Mock logging
logging.basicConfig(level=logging.INFO)

async def test_gemini_client():
    print("Initializating GeminiClient...")
    import google.generativeai as genai
    from agent.config import settings
    genai.configure(api_key=settings.GEMINI_API_KEY)
    
    print("Available models:")
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(m.name)
    except Exception as e:
        print(f"Error listing models: {e}")

    try:
        client = GeminiClient()

        print("Client initialized.")
        
        messages = [
            Message(role="user", content="Hello, are you working?")
        ]
        
        print("Sending message...")
        # Use _generate_response or generic generate_response if base class exposes it
        # Inspect showed LLMClient probably has a public method that calls _generate_response 
        # But we can call _generate_response directly for testing logic
        response = await client._generate_response(messages)
        
        print("Response received:")
        print(response)
        
        if response.get("content"):
            print("SUCCESS: Content found in response.")
        else:
            print("FAILURE: No content in response.")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_gemini_client())
