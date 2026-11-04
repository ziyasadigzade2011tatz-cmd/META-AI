from pathlib import Path
import os
import json
import math
import sqlite3
import urllib.request

DB = str(Path(os.environ.get('META_DATA_DIR',str(Path.home()/'META')))/'legacy_memory.db')
MODEL = "embeddinggemma"


def embed(texts):
    data = json.dumps({
        "model": MODEL,
        "input": texts
    }).encode("utf-8")

    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/embed",
        data=data,
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)["embeddings"]


def initialize():
    with sqlite3.connect(DB) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS memory_vectors (
                memory_id INTEGER PRIMARY KEY,
                model TEXT NOT NULL,
                vector TEXT NOT NULL
            )
        """)


def search(query, limit=8):
    initialize()

    with sqlite3.connect(DB) as db:
        memories = db.execute(
            "SELECT id, fact FROM memories ORDER BY id DESC LIMIT 200"
        ).fetchall()

        if not memories:
            return []

        existing = {
            row[0]: json.loads(row[1])
            for row in db.execute(
                "SELECT memory_id, vector FROM memory_vectors WHERE model = ?",
                (MODEL,)
            )
        }

        missing = [
            (mid, fact) for mid, fact in memories
            if mid not in existing
        ]

        for start in range(0, len(missing), 16):
            batch = missing[start:start + 16]
            vectors = embed([fact for _, fact in batch])

            for (mid, _), vector in zip(batch, vectors):
                existing[mid] = vector
                db.execute(
                    """
                    INSERT OR REPLACE INTO memory_vectors
                    (memory_id, model, vector)
                    VALUES (?, ?, ?)
                    """,
                    (mid, MODEL, json.dumps(vector))
                )

        db.commit()

    query_vector = embed([query])[0]
    results = []

    for mid, fact in memories:
        vector = existing.get(mid)
        if not vector or len(vector) != len(query_vector):
            continue

        similarity = sum(
            a * b for a, b in zip(query_vector, vector)
        )

        if similarity >= 0.35:
            results.append({
                "id": mid,
                "fact": fact,
                "score": round(similarity, 3)
            })

    return sorted(
        results,
        key=lambda item: item["score"],
        reverse=True
    )[:limit]
