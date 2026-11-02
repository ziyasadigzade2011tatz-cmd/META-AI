from pathlib import Path

path = Path(r"D:\META\Core\agent_chat.py")
code = path.read_text(encoding="utf-8-sig")

old = '''"Всегда отвечай на языке пользователя. "
                "Если пользователь пишет по-русски, "
                "отвечай только по-русски. "'''

new = '''"Язык общения определяется языком пользователя. "
                "Если сообщение на русском языке, весь ответ "
                "должен быть на русском языке. "
                "Не используй китайские иероглифы и не смешивай "
                "русский с другими языками, кроме необходимых "
                "названий, терминов и фрагментов кода. "
                "Для приветствия отвечай коротко, например: "
                "Привет! У меня всё хорошо, спасибо. А у тебя? "'''

if old not in code:
    raise SystemExit(
        "Language instruction not found. No changes made."
    )

updated = code.replace(old, new, 1)

old_options = '''"num_ctx": 4096,
                    "num_predict": 256'''

new_options = '''"num_ctx": 4096,
                    "num_predict": 256,
                    "temperature": 0.2'''

if old_options not in updated:
    raise SystemExit(
        "Generation settings not found. No changes made."
    )

updated = updated.replace(old_options, new_options, 1)

backup = path.with_name("agent_chat_before_language_fix.py")
backup.write_text(code, encoding="utf-8")

path.write_text(updated, encoding="utf-8")

print("META Russian Language Fix installed")
