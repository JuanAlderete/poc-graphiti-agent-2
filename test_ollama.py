import asyncio
from openai import AsyncOpenAI

async def main():
    try:
        client = AsyncOpenAI(
            api_key="ollama",
            base_url="http://127.0.0.1:11434/v1",
            timeout=10.0
        )
        response = await client.embeddings.create(
            input=["Test sentence one.", "Test sentence two."],
            model="nomic-embed-text",
        )
        print("Embeddings generated successfully. Dims:", len(response.data[0].embedding))
    except Exception as e:
        print("Error during embeddings:", e)

if __name__ == "__main__":
    asyncio.run(main())
