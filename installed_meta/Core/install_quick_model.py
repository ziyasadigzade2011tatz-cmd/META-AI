from pathlib import Path
import re

path = Path(r"D:\META\Core\agent_chat.py")
code = path.read_text(encoding="utf-8-sig")

backup = path.with_name("agent_chat_before_quick_model.py")
backup.write_text(code, encoding="utf-8")

pattern = r'(^[ \t]*)model, _ = select_model\(original\)'
match = re.search(pattern, code, flags=re.MULTILINE)

if not match:
    raise SystemExit("Model router not found. No changes made.")

indent = match.group(1)

replacement = (
    indent + 'model, _ = select_model(original)\n'
    + indent + 'if model == "meta:latest":\n'
    + indent + '    model = "qwen2.5:3b"\n'
)

code = re.sub(pattern, lambda m: replacement, code, count=1)

# Correct a previous optional patch if it is present.
code = code.replace(
    'if model == "meta:latest":\n            model = "qwen3:4b"',
    'if model == "meta:latest":\n            model = "qwen2.5:3b"'
)

path.write_text(code, encoding="utf-8")
print("META Quick Model installed")
