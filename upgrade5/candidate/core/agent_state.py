import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path(r"D:\META\Memory\agent_state.db")

AGENT_PERMISSIONS = {
    "Planner": set(),
    "Files": {"list_files", "read_file"},
    "Coder": {"list_files", "read_file"},
    "Writer": set(),
    "Teacher": set(),
    "General": set(),
}


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB, timeout=10)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS agent_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    connection.commit()
    return connection


def save_event(agent, session_id, role, content):
    if agent not in AGENT_PERMISSIONS:
        raise ValueError("Unknown agent")

    with connect() as connection:
        connection.execute(
            """INSERT INTO agent_events
            (agent, session_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            (
                agent,
                session_id,
                role,
                content,
                datetime.now(timezone.utc).isoformat()
            )
        )


def load_history(agent, session_id, limit=12):
    if agent not in AGENT_PERMISSIONS:
        raise ValueError("Unknown agent")

    with connect() as connection:
        rows = connection.execute(
            """SELECT role, content FROM (
                SELECT id, role, content
                FROM agent_events
                WHERE agent = ? AND session_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC""",
            (agent, session_id, max(1, min(limit, 50)))
        ).fetchall()

    return [
        {"role": role, "content": content}
        for role, content in rows
    ]


def allowed(agent, tool):
    return tool in AGENT_PERMISSIONS.get(agent, set())
