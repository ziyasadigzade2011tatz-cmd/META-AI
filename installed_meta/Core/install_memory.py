from pathlib import Path

path = Path(r"D:\META\Core\main.py")
original = path.read_text(encoding="utf-8-sig")

if "from memory import" in original:
    raise SystemExit("Memory already connected. No changes made.")

old_import = "from pydantic import BaseModel"
new_import = (
    "from pydantic import BaseModel\n"
    "from memory import prepare_messages, recall, forget"
)

old_selection = "model, task = select_model(request.messages)"
new_selection = (
    "messages = prepare_messages(request.messages)\n"
    "    model, task = select_model(messages)"
)

old_messages = '"messages": request.messages'
new_messages = '"messages": messages'

if original.count(old_import) != 1:
    raise SystemExit("Import marker not found. File unchanged.")

if original.count(old_selection) != 2:
    raise SystemExit("Router markers not found. File unchanged.")

if original.count(old_messages) != 2:
    raise SystemExit("Message markers not found. File unchanged.")

updated = original.replace(old_import, new_import)
updated = updated.replace(old_selection, new_selection)
updated = updated.replace(old_messages, new_messages)

updated += '''

@app.get("/memory")
async def list_memories():
    return {"memories": recall()}


@app.delete("/memory/{memory_id}")
async def delete_memory(memory_id: int):
    deleted = forget(memory_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Memory not found"
        )
    return {"deleted": True, "id": memory_id}
'''

backup = path.with_name("main_before_memory.py")
backup.write_text(original, encoding="utf-8")
path.write_text(updated, encoding="utf-8")

print("Memory Engine connected successfully")
