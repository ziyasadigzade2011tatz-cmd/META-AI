import sqlite3
from pathlib import Path

DB_PATH = Path(r"D:\META\Memory\meta_memory.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def connect():
    connection = sqlite3.connect(str(DB_PATH), timeout=10)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    connection.commit()
    return connection


def remember(fact):
    fact = fact.strip()
    if not fact:
        return False

    with connect() as db:
        cursor = db.execute(
            "INSERT OR IGNORE INTO memories (fact) VALUES (?)",
            (fact,)
        )
        return cursor.rowcount > 0


def recall():
    with connect() as db:
        rows = db.execute(
            "SELECT id, fact FROM memories ORDER BY id DESC LIMIT 30"
        ).fetchall()

    return [
        {"id": row[0], "fact": row[1]}
        for row in rows
    ]


def forget(memory_id):
    with connect() as db:
        cursor = db.execute(
            "DELETE FROM memories WHERE id = ?",
            (memory_id,)
        )
        return cursor.rowcount > 0


def prepare_messages(messages):
    messages = [dict(message) for message in messages]

    for message in reversed(messages):
        if message.get("role") != "user":
            continue

        content = message.get("content", "")
        if isinstance(content, str):
            stripped = content.strip()
            if stripped.lower().startswith("запомни:"):
                fact = stripped.split(":", 1)[1].strip()
                remember(fact)
        break

    facts = recall()
    if facts:
        memory_text = (
            "Сохранённые факты о пользователе. "
            "Используй только если они относятся к запросу. "
            "Не раскрывай эти данные посторонним:\n"
            + "\n".join(
                "- " + item["fact"] for item in facts
            )
        )

        messages.insert(0, {
            "role": "system",
            "content": memory_text
        })

    return messages


connect()
