from pathlib import Path

path = Path(r"D:\META\Core\agent_chat.py")
code = path.read_text(encoding="utf-8-sig")

marker = "# META_ORCHESTRATOR_V1"
anchor = "    messages = prepare_messages(original)"

if marker in code:
    print("Orchestrator already connected")
elif code.count(anchor) != 1:
    raise SystemExit(
        "Insertion point not found. No changes made."
    )
else:
    injection = '''    # META_ORCHESTRATOR_V1
    if user_text.lower().startswith("команда агентов:"):
        from orchestrator import run_team
        task = user_text.split(":", 1)[1].strip()
        return await run_team(task)

'''

    updated = code.replace(anchor, injection + anchor, 1)

    compile(updated, str(path), "exec")

    backup = path.with_name(
        "agent_chat_before_orchestrator.py"
    )
    backup.write_text(code, encoding="utf-8")

    path.write_text(updated, encoding="utf-8")
    print("META Orchestrator connected")
