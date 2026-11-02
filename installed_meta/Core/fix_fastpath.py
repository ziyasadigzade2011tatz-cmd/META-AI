from pathlib import Path

path = Path(r"D:\META\Core\agent_chat.py")
code = path.read_text(encoding="utf-8-sig")

start = code.find("    # META_FAST_PATH_V1")
end = code.find("    messages = prepare_messages(original)", start)

if start == -1 or end == -1:
    raise SystemExit("Fast Path block not found. File unchanged.")

replacement = '''    # META_FAST_PATH_V2
    import re as fast_re

    read_command = fast_re.search(
        r"(?:прочитай|прочти|read)\\s+"
        r"(?:мне\\s+)?(?:файл\\s+)?"
        r"([\\w./\\\\-]+\\.(?:txt|md|py|json|html|css|js|csv|yaml|yml))\\b",
        user_text,
        fast_re.IGNORECASE
    )

    if read_command:
        filename = read_command.group(1)
        try:
            content = read_file(filename)
            print("META FAST PATH: read_file", filename)
            return "Содержимое файла " + filename + ":\\n\\n" + content
        except Exception as error:
            return "Ошибка чтения файла: " + str(error)

'''

updated = code[:start] + replacement + code[end:]
path.write_text(updated, encoding="utf-8")

print("META Fast Path V2 installed")
