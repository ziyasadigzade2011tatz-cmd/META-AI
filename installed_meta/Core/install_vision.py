from pathlib import Path

path = Path(r"D:\META\Core\agent_chat.py")
code = path.read_text(encoding="utf-8-sig")

marker = "# META_VISION_V1"
anchor = "    messages = prepare_messages(original)"

if marker in code:
    print("Vision already connected")
elif code.count(anchor) != 1:
    raise SystemExit(
        "Expected insertion point not found. File unchanged."
    )
else:
    injection = '''    # META_VISION_V1
    from vision import has_images, vision_reply

    if has_images(original):
        print("META ACTIVE AGENT: Vision Agent", flush=True)
        return await vision_reply(original)

'''

    updated = code.replace(
        anchor,
        injection + anchor,
        1
    )

    backup = path.with_name(
        "agent_chat_before_vision.py"
    )
    backup.write_text(code, encoding="utf-8")

    path.write_text(updated, encoding="utf-8")
    print("META Vision Agent connected")
