from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx

app = FastAPI(title="META Core", version="0.2.0")

OLLAMA_URL = "http://127.0.0.1:11434"

MODELS = {
    "general": "meta:latest",
    "coding": "qwen2.5-coder:7b"
}


class ChatRequest(BaseModel):
    messages: list[dict]


def select_model(messages):
    last_user_message = ""

    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, str):
                last_user_message = content.lower()
            break

    coding_keywords = [
        "python", "javascript", "typescript",
        "html", "css", "sql", "fastapi",
        "программ", "напиши код",
        "исправь код", "ошибка в коде",
        "скрипт", "debug",
        "write code", "fix code"
    ]

    if any(word in last_user_message for word in coding_keywords):
        return MODELS["coding"], "coding"

    return MODELS["general"], "general"


@app.get("/")
async def home():
    return {
        "name": "META Core",
        "status": "online",
        "version": "0.2.0"
    }


@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{OLLAMA_URL}/api/tags"
            )
            response.raise_for_status()

        return {
            "status": "online",
            "ollama": "connected",
            "router": "active"
        }

    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=str(error)
        )


@app.post("/chat")
async def chat(request: ChatRequest):
    model, task_type = select_model(request.messages)

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": model,
                    "messages": request.messages,
                    "stream": False,
                    "options": {
                        "num_ctx": 8192
                    }
                }
            )

            response.raise_for_status()
            data = response.json()

        return {
            "assistant": "META",
            "task_type": task_type,
            "internal_model": model,
            "reply": data["message"]["content"]
        }

    except httpx.HTTPStatusError as error:
        raise HTTPException(
            status_code=error.response.status_code,
            detail=error.response.text
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )
