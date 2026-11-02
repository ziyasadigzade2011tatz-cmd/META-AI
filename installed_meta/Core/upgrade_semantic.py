from pathlib import Path

path = Path(r"D:\META\Core\memory.py")
code = path.read_text(encoding="utf-8-sig")

marker = "# META_SEMANTIC_V3"

if marker in code:
    print("Semantic memory already connected")
else:
    code += """

# META_SEMANTIC_V3
_keyword_search = relevant_memories


def relevant_memories(query, limit=8):
    try:
        from semantic import search
        results = search(query, limit)
        if results:
            return results
    except Exception as error:
        print("Semantic search fallback:", error)

    return _keyword_search(query, limit)
"""
    path.write_text(code, encoding="utf-8")
    print("META Memory Engine 3.0 connected")
