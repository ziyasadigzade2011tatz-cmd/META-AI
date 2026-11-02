"""Versioned proposals using agent_pending's store and shared approval lock."""
import base64
import contextlib
import difflib
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from .workspace import Workspace, digest, validate_content, MAX_TOTAL


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.meta40-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def store():
    import agent_pending
    return agent_pending.STORE


@contextlib.contextmanager
def approval_lock():
    import msvcrt
    with (store()/'approval.lock').open('a+b') as f:
        f.seek(0); f.write(b'0'); f.flush(); f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        try: yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def identifier(pid):
    if not isinstance(pid, str) or not re.fullmatch('[a-f0-9]{32}', pid):
        raise ValueError('Invalid proposal ID')
    return pid


def is_ours(pid):
    p = store()/(identifier(pid)+'.json')
    return p.is_file() and json.loads(p.read_text(encoding='utf-8')).get('kind') == 'meta40'


def stage(root, edits, snapshot):
    from agent_tools import WORKSPACE
    ws = Workspace(root)
    if not ws.root.is_relative_to(Path(WORKSPACE).resolve()):
        raise ValueError('Project must be within existing META Projects')
    if not 1 <= len(edits) <= 12 or sum(len(v.encode('utf-8')) for v in edits.values()) > MAX_TOTAL:
        raise ValueError('Proposal limit: 12 files / 100 KB')
    if len({n.casefold() for n in edits}) != len(edits):
        raise ValueError('Case-insensitive duplicate paths')
    changes = []
    for name, content in edits.items():
        validate_content(name, content)
        target = ws.path(name)
        old = target.read_bytes() if target.exists() else None
        if digest(old) != digest(snapshot.get(name)):
            raise RuntimeError('File changed during task or was excluded from snapshot: '+name)
        if old == content.encode('utf-8'):
            continue
        changes.append({'path':name, 'content':content, 'expected_hash':digest(old)})
    if not changes:
        return None
    pid = uuid.uuid4().hex
    atomic_json(store()/(pid+'.json'), {'id':pid, 'kind':'meta40', 'created':time.time(),
                'root':str(ws.root), 'files':changes})
    return {'id':pid, 'status':'pending', 'files':[x['path'] for x in changes], 'applied':False}


def load(pid):
    from agent_tools import WORKSPACE
    p = store()/(identifier(pid)+'.json')
    record = json.loads(p.read_text(encoding='utf-8'))
    if record.get('kind') != 'meta40' or record.get('id') != pid:
        raise ValueError('Proposal mismatch')
    if time.time()-record['created'] > 86400:
        raise ValueError('Proposal expired (24 hours)')
    ws = Workspace(record['root'])
    if not ws.root.is_relative_to(Path(WORKSPACE).resolve()):
        raise ValueError('Outside Projects')
    files = record['files']
    if not 1 <= len(files) <= 12 or sum(len(x['content'].encode()) for x in files) > MAX_TOTAL:
        raise ValueError('Invalid proposal size')
    if len({x['path'].casefold() for x in files}) != len(files):
        raise ValueError('Duplicate paths')
    checked = []
    for change in files:
        name, content = change['path'], change['content']
        validate_content(name, content)
        target = ws.path(name)
        current = target.read_bytes() if target.exists() else None
        if digest(current) != change['expected_hash']:
            raise RuntimeError('File changed since task: '+name)
        checked.append((target, current, content.encode('utf-8')))
    return p, record, checked


def preview(pid):
    _, record, checked = load(pid)
    diffs = []
    for item, (_, old, new) in zip(record['files'], checked):
        diffs.append(''.join(difflib.unified_diff(
            (old or b'').decode('utf-8').splitlines(True), new.decode('utf-8').splitlines(True),
            fromfile='before/'+item['path'], tofile='after/'+item['path'])))
    return {'id':pid, 'status':'pending', 'path':', '.join(x['path'] for x in record['files']),
            'files':[x['path'] for x in record['files']], 'diff':'\n'.join(diffs), 'applied':False}


def replace_bytes(path, raw):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.meta40-')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def approve(pid):
    with approval_lock():
        proposal_file, record, checked = load(pid)
        receipt = store()/'meta40_receipts'/(pid+'.json')
        if receipt.exists():
            raise RuntimeError('Prior application found; inspect rollback receipt before retry')
        journal = {'id':pid, 'root':record['root'], 'status':'applying', 'files':[
            {'path':x['path'], 'old':base64.b64encode(old).decode() if old is not None else None,
             'new_hash':digest(new)} for x, (_, old, new) in zip(record['files'], checked)]}
        atomic_json(receipt, journal)
        written = []
        made = []
        try:
            for target, old, new in checked:
                missing = []
                parent = target.parent
                while not parent.exists():
                    missing.append(parent); parent = parent.parent
                for parent in reversed(missing):
                    parent.mkdir(); made.append(parent)
            # Recheck every file after directory preparation.
            load(pid)
            for target, old, new in checked:
                replace_bytes(target, new)
                written.append((target, old))
            journal['status'] = 'applied'
            atomic_json(receipt, journal)
            proposal_file.unlink()
            return {'id':pid, 'status':'applied', 'applied':True, 'rollback_receipt':str(receipt)}
        except BaseException:
            failures = []
            for target, old in reversed(written):
                try:
                    if old is None: target.unlink()
                    else: replace_bytes(target, old)
                except OSError as exc: failures.append(str(exc))
            for parent in reversed(made):
                try: parent.rmdir()
                except OSError: pass
            journal['status'] = 'rollback_incomplete' if failures else 'rolled_back'
            journal['errors'] = failures
            atomic_json(receipt, journal)
            raise


def rollback(pid):
    """Explicit local CLI action. Refuses to overwrite later user edits."""
    from agent_tools import WORKSPACE
    with approval_lock():
        receipt = store()/'meta40_receipts'/(identifier(pid)+'.json')
        data = json.loads(receipt.read_text(encoding='utf-8'))
        ws = Workspace(data['root'])
        if not ws.root.is_relative_to(Path(WORKSPACE).resolve()):
            raise ValueError('Outside Projects')
        checked = []
        for entry in data['files']:
            p = ws.path(entry['path'])
            old = base64.b64decode(entry['old'], validate=True) if entry['old'] is not None else None
            now = p.read_bytes() if p.exists() else None
            if digest(now) not in (entry['new_hash'], digest(old)):
                raise RuntimeError('Later edits detected; rollback refused: '+entry['path'])
            checked.append((p, old))
        for p, old in checked:
            if old is None: p.unlink(missing_ok=True)
            else: replace_bytes(p, old)
        data['status'] = 'rolled_back'
        atomic_json(receipt, data)
        return {'id':pid, 'status':'rolled_back'}


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 3 or sys.argv[1] != 'rollback':
        raise SystemExit('Usage: python -m meta40.proposals rollback PROPOSAL_ID')
    print(rollback(sys.argv[2]))
