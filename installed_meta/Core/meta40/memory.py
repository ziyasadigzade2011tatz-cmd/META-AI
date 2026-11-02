"""Compact per-project task history. Stores outcomes; never asserts pending edits were applied."""
from __future__ import annotations
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

MAX_ITEMS = 12


def _path(state_dir, root):
    ident = hashlib.sha256(str(Path(root).resolve()).casefold().encode('utf-8')).hexdigest()
    return Path(state_dir) / 'memory' / (ident + '.json')


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.memory-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def load_history(state_dir, root):
    path = _path(state_dir, root)
    try:
        result = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(result, list): return [x for x in result[-MAX_ITEMS:] if isinstance(x, dict)]
    except (FileNotFoundError, ValueError, OSError):
        pass
    return []


def save_outcome(state_dir, root, task, result):
    """Failed tasks are recorded too, clearly labelled. No unconditional 'learned' claim."""
    rows = load_history(state_dir, root)
    rows.append({
        'time': int(time.time()),
        'task': str(task)[:1200],
        'status': str(result.get('status', 'unknown'))[:40],
        'summary': str(result.get('summary', ''))[:1700],
        'proposal_id': (result.get('proposal') or {}).get('id'),
        'pending_is_not_applied': result.get('status') == 'pending',
    })
    _atomic_write(_path(state_dir, root), rows[-MAX_ITEMS:])


def memory_context(state_dir, root, limit=5):
    rows = load_history(state_dir, root)[-limit:]
    return [{'task':r.get('task'), 'status':r.get('status'),
             'summary':r.get('summary'), 'pending_is_not_applied':r.get('pending_is_not_applied', False)}
            for r in rows]
