from pathlib import Path

path = Path(r"D:\META\Core\agent_chat.py")
code = path.read_text(encoding="utf-8-sig")

marker = "# META_FAST_PATH_V1"

if marker in code:
    print("Fast Path already installed")
else:
    anchor = "    messages = prepare_messages(original)"

    if code.count(anchor) != 1:
        raise SystemExit(
            "Expected insertion point not found. No changes."
        )

    injection = '''    # META_FAST_PATH_V1
    import re as fast_re

    read_command = fast_re.search(
        r"(?i)(?:прочитай|прочти|read)\\\\s+"
        r"(?:мне\\\\s+)?(?:файл\\\\s+)?"
        r"([\\\\w./\\\\\\\\-]+\\\\.(?:txt|md|py|json|html|css|js|csv|yaml|yml))",
        user_text
    )

    if read_command:
        filename = read_command.group(1)
        try:
            content = read_file(filename)
            print("META FAST PATH: read_file", filename)
            return (
                "Содержимое файла " + filename + ":\\\\n\\\\n"
                + content
            )
        except Exception as error:
            return "Ошибка чтения файла: " + str(error)

'''

    injection = injection.replace(
        r"\\\\s", r"\\s"
    ).replace(
        r"\\\\w", r"\\w"
    ).replace(
        r"\\\\.", r"\\."
    ).replace(
        r"\\\\n", r"\\n"
    )

    backup = path.with_name("agent_chat_before_fastpath.py")
    backup.write_text(code, encoding="utf-8")

    updated = code.replace(anchor, injection + anchor, 1)
    path.write_text(updated, encoding="utf-8")

    print("META Fast Path installed")
