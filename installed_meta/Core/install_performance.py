from pathlib import Path
import re

path = Path(r"D:\META\Core\agent_chat.py")
code = path.read_text(encoding="utf-8-sig")

marker = "# META_PERFORMANCE_ROUTER_V1"

if marker in code:
    raise SystemExit("Performance Router already connected.")

anchor = "    async with httpx.AsyncClient("

injection = '''    # META_PERFORMANCE_ROUTER_V1
    from performance_router import choose_performance

    performance = choose_performance(
        user_text,
        coding=(model == "qwen2.5-coder:7b")
    )

    if not file_task:
        model = performance["model"]

    generation_options = (
        {"num_ctx": 8192, "num_predict": 1024, "temperature": 0.2}
        if file_task else performance["options"]
    )

    print(
        "META PERFORMANCE:",
        "agent-tools" if file_task else performance["mode"],
        "| MODEL:", model
    )

'''

pattern = (
    r'"options":\\s*\\{'
    r'\\s*"num_ctx":\\s*4096,'
    r'\\s*"num_predict":\\s*256,'
    r'\\s*"temperature":\\s*0\\.2'
    r'\\s*\\}'
)

if code.count(anchor) != 1:
    raise SystemExit("Insertion point not found. No changes made.")

if len(re.findall(pattern, code)) != 1:
    raise SystemExit("Generation settings differ. No changes made.")

updated = code.replace(anchor, injection + anchor, 1)
updated = re.sub(
    pattern,
    '"options": generation_options',
    updated,
    count=1
)

backup = path.with_name("agent_chat_before_performance.py")
backup.write_text(code, encoding="utf-8")

path.write_text(updated, encoding="utf-8")
print("Performance Router connected")
