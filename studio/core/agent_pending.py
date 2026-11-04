from pathlib import Path
import hashlib
import json
import uuid
import difflib
import sys

from agent_tools import safe_path, ALLOWED_EXTENSIONS

import os
STORE = Path(os.environ.get('META_PENDING_DIR', str(Path.home()/'META'/'pending')))
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


# META_APPROVAL_GUI_36
# Desktop-only approval functions. Never expose these directly through FastAPI.
def _proposal_record(proposal_id):
    import time
    if not (isinstance(proposal_id, str) and len(proposal_id) == 32
            and all(c in '0123456789abcdef' for c in proposal_id)):
        raise ValueError('Invalid proposal ID')
    record_file = STORE / (proposal_id + '.json')
    if not record_file.is_file():
        raise FileNotFoundError('Proposal missing or already processed')
    if time.time() - record_file.stat().st_mtime > 24 * 3600:
        raise ValueError('Proposal expired (24 hours)')
    record = json.loads(record_file.read_text(encoding='utf-8'))
    if record.get('id') != proposal_id:
        raise ValueError('Proposal ID mismatch')
    return record_file, record


def proposal_preview(proposal_id):
    _, record = _proposal_record(proposal_id)
    target, current, diff = inspect(record['path'], record['content'])
    if digest(current) != record['expected_hash']:
        raise RuntimeError('File changed since proposal was created')
    return {'id': proposal_id, 'path': record['path'],
            'status': 'pending', 'diff': diff[:30000], 'applied': False}


def proposal_reject(proposal_id):
    record_file, _ = _proposal_record(proposal_id)
    record_file.unlink()
    return {'status': 'rejected', 'id': proposal_id, 'applied': False}


def proposal_approve(proposal_id):
    import os
    import tempfile
    import msvcrt
    lock_path = STORE / 'approval.lock'
    with lock_path.open('a+b') as lock_file:
        lock_file.seek(0)
        lock_file.write(b'0')
        lock_file.flush()
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            record_file, record = _proposal_record(proposal_id)
            target, current, _ = inspect(record['path'], record['content'])
            if digest(current) != record['expected_hash']:
                raise RuntimeError('File changed since preview; not applied')
            if current == record['content'].encode('utf-8'):
                record_file.unlink()
                return {'status': 'unchanged', 'path': str(target), 'applied': False}
            if current is not None:
                backup = target.with_name(target.name + '.' + proposal_id[:8] + '.bak')
                with backup.open('xb') as handle:
                    handle.write(current)
            # Temporary file created on the same volume for atomic replacement.
            fd, tmp_name = tempfile.mkstemp(prefix='.meta-', suffix='.tmp', dir=target.parent)
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(record['content'].encode('utf-8'))
                    handle.flush()
                    os.fsync(handle.fileno())
                # Revalidate after preview; this is not a hostile-process sandbox.
                checked, latest, _ = inspect(record['path'], record['content'])
                if checked != target or digest(latest) != record['expected_hash']:
                    raise RuntimeError('File changed before write; not applied')
                os.replace(tmp_name, target)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            record_file.unlink()
            return {'status': 'applied', 'path': str(target), 'applied': True}
        finally:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


# META_PROJECT_ENGINE_37
# Extend the existing Desktop-only approval API with multi-file proposals.
_meta36_preview = proposal_preview
_meta36_approve = proposal_approve

def proposal_preview(proposal_id):
    from agent_project37 import preview_project
    import json
    location = STORE / (proposal_id + '.json')
    if location.is_file():
        record = json.loads(location.read_text(encoding='utf-8'))
        if record.get('kind') == 'project37':
            return preview_project(proposal_id)
    return _meta36_preview(proposal_id)

def proposal_approve(proposal_id):
    from agent_project37 import apply_project
    import json
    location = STORE / (proposal_id + '.json')
    if location.is_file():
        record = json.loads(location.read_text(encoding='utf-8'))
        if record.get('kind') == 'project37':
            return apply_project(proposal_id)
    return _meta36_approve(proposal_id)


# META40_PENDING_INTEGRATION
_meta40_previous_preview = proposal_preview
_meta40_previous_approve = proposal_approve

def proposal_preview(proposal_id):
    from meta40.proposals import is_ours, preview
    return preview(proposal_id) if is_ours(proposal_id) else _meta40_previous_preview(proposal_id)

def proposal_approve(proposal_id):
    from meta40.proposals import is_ours, approve
    return approve(proposal_id) if is_ours(proposal_id) else _meta40_previous_approve(proposal_id)


# META5_APPROVAL_COMPATIBILITY
_meta5_previous_preview=proposal_preview
_meta5_previous_approve=proposal_approve
def proposal_preview(proposal_id):
    from meta5.changes import ours,preview
    return preview(proposal_id) if ours(proposal_id) else _meta5_previous_preview(proposal_id)
def proposal_approve(proposal_id):
    from meta5.changes import ours,approve
    return approve(proposal_id) if ours(proposal_id) else _meta5_previous_approve(proposal_id)
