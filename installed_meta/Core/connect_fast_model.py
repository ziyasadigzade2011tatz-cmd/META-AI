from pathlib import Path

path = Path(r"D:\META\Core\agent_chat.py")
code = path.read_text(encoding="utf-8-sig")

old = "        model, _ = select_model(original)"

new = """        model, _ = select_model(original)

        if model == "meta:latest":
            model = "qwen2.5:3b"

        messages.insert(0, {
            "role": "system",
            "content": (
                "Ты — META, персональный ИИ-помощник. "
                "Всегда отвечай на языке пользователя. "
                "Если пользователь пишет по-русски, "
                "отвечай только по-русски. "
                "Отвечай естественно, кратко и понятно. "
                "Не показывай внутренние рассуждения. "
                "Используй сохранённую память, когда она уместна."
            )
        })"""

if code.count(old) != 1:
    raise SystemExit(
        "Expected model selector not found. No changes made."
    )

backup = path.with_name("agent_chat_before_fast_model.py")
backup.write_text(code, encoding="utf-8")

updated = code.replace(old, new, 1)

path.write_text(updated, encoding="utf-8")

print("META Fast Model connected successfully")
