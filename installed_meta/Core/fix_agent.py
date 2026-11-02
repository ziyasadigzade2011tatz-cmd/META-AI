from pathlib import Path

path = Path(r"D:\META\Core\agent_chat.py")
code = path.read_text(encoding="utf-8-sig")

old = "async def agent_completions(request):"
new = "async def agent_completions(request: ChatRequest):"

if old not in code:
    raise SystemExit("Expected function not found. File unchanged.")

code = code.replace(
    "from memory import prepare_messages",
    "from memory import prepare_messages\nfrom pydantic import BaseModel"
)

code = code.replace(
    old,
    """class ChatRequest(BaseModel):
    model: str = "meta-core"
    messages: list[dict]
    stream: bool = False


async def agent_completions(request: ChatRequest):"""
)

path.write_text(code, encoding="utf-8")
print("Agent Chat request validation fixed")
