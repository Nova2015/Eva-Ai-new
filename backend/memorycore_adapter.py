import os
import httpx


MEMORYCORE_URL = os.getenv(
    "MEMORYCORE_URL",
    "http://127.0.0.1:8420",
).rstrip("/")


async def recall_memory(
    query: str,
    session_key: str,
) -> dict:
    payload = {
        "query": query,
        "session_key": session_key,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{MEMORYCORE_URL}/recall",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


async def capture_memory(
    user_content: str,
    assistant_content: str,
    session_key: str,
) -> dict:
    payload = {
        "user_content": user_content,
        "assistant_content": assistant_content,
        "session_key": session_key,
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{MEMORYCORE_URL}/capture",
            json=payload,
        )
        response.raise_for_status()
        return response.json()