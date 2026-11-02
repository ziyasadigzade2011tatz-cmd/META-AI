from pathlib import Path

path = Path(r"D:\META\Core\agent_chat.py")
code = path.read_text(encoding="utf-8-sig")

old = '"options": {"num_ctx": 8192}'
new = '''"think": False,
                "options": {
                    "num_ctx": 4096,
                    "num_predict": 256
                }'''

if old not in code:
    raise SystemExit(
        "Expected settings not found. No changes made."
    )

backup = path.with_name("agent_chat_before_speed.py")
backup.write_text(code, encoding="utf-8")

code = code.replace(old, new, 1)
path.write_text(code, encoding="utf-8")

print("META Fast Response settings installed")
