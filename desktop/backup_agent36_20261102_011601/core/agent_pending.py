from pathlib import Path
import hashlib
import json
import uuid
import difflib
import sys

from agent_tools import safe_path, ALLOWED_EXTENSIONS

STORE = Path(r"D:\META\Memory\pending_changes")
STORE.mkdir(parents=True, exist_ok=True)
LIMIT = 20000


def digest(data):
    if data is None:
        return None
    return hashlib.sha256(data).hexdigest()


def inspect(path, content):
    target = safe_path(path)

    if target.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported extension")

    if len(content.encode("utf-8")) > LIMIT:
        raise ValueError("Content too large")

    if not target.parent.is_dir():
        raise ValueError("Parent folder does not exist")

    if target.exists() and not target.is_file():
        raise ValueError("Not a regular file")

    old = target.read_bytes() if target.exists() else None
    if old is not None and len(old) > 100000:
        raise ValueError("Existing file too large")

    old_text = old.decode("utf-8") if old is not None else ""
    diff = "".join(difflib.unified_diff(
        old_text.splitlines(keepends=True),
        content.splitlines(keepends=True),
        fromfile="before/" + path,
        tofile="after/" + path
    ))

    return target, old, diff


def stage(path, content):
    target, old, diff = inspect(path, content)
    proposal_id = uuid.uuid4().hex

    record = {
        "id": proposal_id,
        "path": path,
        "content": content,
        "expected_hash": digest(old)
    }

    destination = STORE / (proposal_id + ".json")
    with destination.open("x", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)

    return {
        "id": proposal_id,
        "path": path,
        "status": "pending",
        "diff": diff[:30000],
        "applied": False
    }


def apply_local(proposal_id):
    if not (
        len(proposal_id) == 32
        and all(c in "0123456789abcdef" for c in proposal_id)
    ):
        raise ValueError("Invalid proposal ID")

    record_file = STORE / (proposal_id + ".json")
    record = json.loads(record_file.read_text(encoding="utf-8"))

    if record["id"] != proposal_id:
        raise ValueError("Proposal mismatch")

    target, old, diff = inspect(
        record["path"], record["content"]
    )

    if digest(old) != record["expected_hash"]:
        raise RuntimeError(
            "File changed since preview. Approval cancelled."
        )

    print("\nFILE:", target)
    print("\nCHANGES:\n")
    print(diff if diff else "(no differences)")

    answer = input(
        "\nType YES to apply this exact proposal: "
    ).strip()

    if answer != "YES":
        return "CANCELLED"

    # Check again after the user reviews the change.
    checked, current, _ = inspect(
        record["path"], record["content"]
    )

    if checked != target or digest(current) != record["expected_hash"]:
        raise RuntimeError("File changed during approval")

    if current is None:
        with target.open("x", encoding="utf-8") as f:
            f.write(record["content"])
    else:
        backup = target.with_name(
            target.name + "." + proposal_id[:8] + ".bak"
        )
        with backup.open("xb") as f:
            f.write(current)

        # No file changes before explicit YES.
        target.write_text(record["content"], encoding="utf-8")

    record_file.unlink()
    return "APPLIED: " + str(target)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: agent_pending.py PROPOSAL_ID")

    print(apply_local(sys.argv[1]))
