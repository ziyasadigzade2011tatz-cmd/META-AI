from pathlib import Path

path = Path(r"D:\META\Core\main.py")
code = path.read_text(encoding="utf-8-sig")

marker = "# META_AGENT_CHAT_V1"

if marker in code:
    print("Agent Chat already connected")
elif 'app = FastAPI(' not in code or 'class ChatRequest(' not in code:
    print("Unexpected main.py structure. No changes made.")
else:
    backup = Path(r"D:\META\Core\main_before_agent_chat.py")
    backup.write_text(code, encoding="utf-8")

    code += '''

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
'''
    path.write_text(code, encoding="utf-8")
    print("META Agent Chat connected")
