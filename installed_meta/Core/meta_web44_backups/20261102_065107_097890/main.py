import json
import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from memory import prepare_messages, recall, forget

app = FastAPI(title="META Core", version="0.3.0")

OLLAMA_URL = "http://127.0.0.1:11434"


class ChatRequest(BaseModel):
    messages: list[dict]
    model: str = "meta-core"
    stream: bool = False


def select_model(messages):
    keywords = [
        "python", "javascript", "typescript",
        "html", "css", "sql", "fastapi",
        "программ", "напиши код", "исправь код",
        "ошибка в коде", "скрипт", "debug",
        "write code", "fix code"
    ]

    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, str):
                if any(word in content.lower() for word in keywords):
                    return "qwen2.5-coder:7b", "coding"
            break

    return "meta:latest", "general"


@app.get("/")
async def home():
    return {
        "name": "META Core",
        "version": "0.3.0",
        "status": "online"
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

    except httpx.HTTPError as error:
        raise HTTPException(status_code=503, detail=str(error))


@app.get("/v1/models")
async def models():
    return {
        "object": "list",
        "data": [{
            "id": "meta-core",
            "object": "model",
            "created": 0,
            "owned_by": "META"
        }]
    }


@app.post("/chat")
async def chat(request: ChatRequest):
    messages = prepare_messages(request.messages)
    model, task = select_model(messages)

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {"num_ctx": 8192}
                }
            )
            response.raise_for_status()

        return {
            "assistant": "META",
            "task_type": task,
            "internal_model": model,
            "reply": response.json()["message"]["content"]
        }

    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail=str(error))


@app.post("/v1/chat/completions")
async def completions(request: ChatRequest):
    messages = prepare_messages(request.messages)
    model, task = select_model(messages)

    payload = {
        "model": model,
        "messages": messages,
        "stream": request.stream,
        "options": {"num_ctx": 8192}
    }

    completion_id = "chatcmpl-" + uuid.uuid4().hex
    created = int(time.time())

    if not request.stream:
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json=payload
                )
                response.raise_for_status()

            data = response.json()

            return {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": "meta-core",
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": data["message"].get("content", "")
                    },
                    "finish_reason": "stop"
                }]
            }

        except httpx.HTTPError as error:
            raise HTTPException(status_code=502, detail=str(error))

    async def generate():
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=15,
                    read=300,
                    write=30,
                    pool=15
                )
            ) as client:
                async with client.stream(
                    "POST",
                    f"{OLLAMA_URL}/api/chat",
                    json=payload
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line:
                            continue

                        data = json.loads(line)
                        content = data.get(
                            "message", {}
                        ).get("content", "")

                        if content:
                            chunk = {
                                "id": completion_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": "meta-core",
                                "choices": [{
                                    "index": 0,
                                    "delta": {"content": content},
                                    "finish_reason": None
                                }]
                            }

                            yield (
                                "data: "
                                + json.dumps(chunk, ensure_ascii=False)
                                + "\n\n"
                            )

            final_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": "meta-core",
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop"
                }]
            }

            yield "data: " + json.dumps(final_chunk) + "\n\n"
            yield "data: [DONE]\n\n"

        except Exception as error:
            error_message = {
                "error": {"message": str(error)}
            }
            yield "data: " + json.dumps(error_message) + "\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream"
    )


@app.get("/memory")
async def list_memories():
    return {"memories": recall()}


@app.delete("/memory/{memory_id}")
async def delete_memory(memory_id: int):
    deleted = forget(memory_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Memory not found"
        )
    return {"deleted": True, "id": memory_id}


# META_AGENT_RUNTIME_V1

from agent_tools import list_files, read_file, create_file
from pydantic import BaseModel as AgentBaseModel


class CreateFileRequest(AgentBaseModel):
    path: str
    content: str


@app.get("/agent/files")
async def agent_files(folder: str = "."):
    try:
        return {"files": list_files(folder)}
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/agent/read")
async def agent_read(path: str):
    try:
        return {"path": path, "content": read_file(path)}
    except (ValueError, OSError, UnicodeError) as error:
        raise HTTPException(status_code=400, detail=str(error))


# META_APPROVAL_STAGE_33
# Direct creation is disabled until explicit approval is implemented.
@app.post("/agent/create")
async def agent_create(request: CreateFileRequest):
    raise HTTPException(
        status_code=403,
        detail="Direct file creation disabled. Use /agent/propose."
    )


@app.post("/agent/propose")
async def agent_propose(request: CreateFileRequest):
    import difflib
    from agent_tools import safe_path, ALLOWED_EXTENSIONS

    try:
        path = safe_path(request.path)

        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError("Unsupported file type")

        if len(request.content.encode("utf-8")) > 20000:
            raise ValueError("Content too large")

        if not path.parent.is_dir():
            raise ValueError("Parent folder does not exist")

        if path.exists() and not path.is_file():
            raise ValueError("Target is not a regular file")

        if path.exists() and path.stat().st_size > 100000:
            raise ValueError("Existing file too large")

        previous = (
            path.read_text(encoding="utf-8")
            if path.exists() else ""
        )

        diff = "".join(difflib.unified_diff(
            previous.splitlines(keepends=True),
            request.content.splitlines(keepends=True),
            fromfile="current/" + request.path,
            tofile="proposed/" + request.path
        ))

        return {
            "status": "preview_only",
            "path": request.path,
            "operation": "modify" if path.exists() else "create",
            "diff": diff[:30000],
            "changed": previous != request.content,
            "applied": False,
            "message": "No files were changed"
        }

    except (ValueError, OSError, UnicodeError) as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )



# META_AGENT_STAGE_34
@app.post("/agent/stage")
async def agent_stage(request: CreateFileRequest):
    from agent_pending import stage
    try:
        return stage(request.path, request.content)
    except (ValueError, OSError, UnicodeError) as error:
        raise HTTPException(status_code=400, detail=str(error))


# META_AGENT_CHAT_V1
from agent_chat import agent_completions

app.router.routes[:] = [
    route for route in app.router.routes
    if not (
        getattr(route, "path", None) == "/v1/chat/completions"
        and "POST" in getattr(route, "methods", set())
    )
]

app.add_api_route(
    "/v1/chat/completions",
    agent_completions,
    methods=["POST"]
)

# META40_CORE_INTEGRATION
from meta40.api import install as install_meta40
install_meta40(app)
