from pathlib import Path

path = Path(r"D:\META\Core\agent_chat.py")
code = path.read_text(encoding="utf-8-sig")

marker = "# META_AGENT_REGISTRY_V1"
anchor = "    async with httpx.AsyncClient("

if marker in code:
    print("Agent Registry already installed.")
elif code.count(anchor) != 1:
    raise SystemExit(
        "Insertion point not found. File unchanged."
    )
else:
    injection = '''    # META_AGENT_REGISTRY_V1
    from agent_registry import AGENTS, route_agent

    agent_id = route_agent(user_text, file_task)

    messages.insert(0, {
        "role": "system",
        "content": AGENTS[agent_id]["instruction"]
    })

    print(
        "META ACTIVE AGENT:",
        AGENTS[agent_id]["name"],
        flush=True
    )

'''

    updated = code.replace(
        anchor, injection + anchor, 1
    )

    backup = path.with_name(
        "agent_chat_before_registry.py"
    )
    backup.write_text(code, encoding="utf-8")

    path.write_text(updated, encoding="utf-8")
    print("META Agent Registry connected")
