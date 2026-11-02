from pathlib import Path
import re

path = Path(r"D:\META\Core\agent_chat.py")
code = path.read_text(encoding="utf-8-sig")

marker = "# META_PERFORMANCE_ROUTER_V1"

if marker in code:
    raise SystemExit("Performance Router already installed.")

anchor = "    async with httpx.AsyncClient("

if code.count(anchor) != 1:
    raise SystemExit("Insertion point not found. No changes made.")

pattern = r'"options"\s*:\s*\{[^{}]*\}'

matches = list(re.finditer(pattern, code))

if len(matches) != 1:
    raise SystemExit(
        f"Found {len(matches)} options blocks. "
        "No changes made."
    )

injection = '''    # META_PERFORMANCE_ROUTER_V1
    from performance_router import choose_performance

    performance = choose_performance(
        user_text,
        coding=(model == "qwen2.5-coder:7b")
    )

    if not file_task:
        model = performance["model"]

    generation_options = (
        {
            "num_ctx": 8192,
            "num_predict": 1024,
            "temperature": 0.2
        }
        if file_task else performance["options"]
    )

    print(
        "META PERFORMANCE:",
        "agent-tools" if file_task else performance["mode"],
        "| MODEL:", model,
        flush=True
    )

'''

updated = re.sub(
    pattern,
    '"options": generation_options',
    code,
    count=1
)

updated = updated.replace(anchor, injection + anchor, 1)

backup = path.with_name(
    "agent_chat_before_performance.py"
)
backup.write_text(code, encoding="utf-8")

path.write_text(updated, encoding="utf-8")

print("META Performance Router installed successfully")
