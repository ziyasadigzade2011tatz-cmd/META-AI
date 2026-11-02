# META_PROJECT_ENGINE_37
"""Stage and approve multi-file edits within D:\\META\\Projects.

No shell execution, no automatic application. Desktop's authenticated approval
route is the only intended caller for proposal_approve().
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid
import msvcrt

from agent_tools import safe_path, ALLOWED_EXTENSIONS
from agent_pending import STORE, LIMIT, inspect, digest

MAX_FILES = 12
MAX_TOTAL = 100_000
EXPIRY = 24 * 3600
VALID_ID = re.compile(r'^[a-f0-9]{32}$')
FILE = re.compile(r'^[\w.\-/ ]+\.(?:py|js|json|html|css|md|txt|yaml|yml|csv)$', re.I)
FENCE = re.compile(r'```([^\n`]*)\n([\s\S]*?)```')
FILENAME_LINE = re.compile(r'(?:^|\n)\s*(?:#{1,5}\s*)?(?:Файл|File|Path)\s*:\s*`?([\w.\-/ ]+\.[a-zA-Z0-9]+)`?\s*$', re.I)

def _validate(path, content):
    if not isinstance(path, str) or not FILE.fullmatch(path.strip()):
        raise ValueError('Invalid relative filename: ' + str(path))
    if Path(path).is_absolute() or ':' in path or '\\' in path or path.startswith('/'):
        raise ValueError('Absolute paths are forbidden')
    target, old, diff = inspect(path, content)
    if target.is_symlink() or any(p.is_symlink() for p in target.parents if p != target.anchor):
        raise ValueError('Symlinks are not allowed')
    if target.suffix.lower() == '.py':
        ast.parse(content, filename=path)
    if target.suffix.lower() == '.json':
        json.loads(content)
    return target, old, diff

def parse_coder_files(text):
    """Parse separately named fenced code blocks. Never guess a filename."""
    if '### Результат Coder' in text:
        text = text.split('### Результат Coder', 1)[1].split('\n### ', 1)[0]
    files = []
    seen = set()
    for match in FENCE.finditer(text):
        header = match.group(1).strip()
        content = match.group(2)
        words = header.split()
        named = None
        for word in words:
            if word.startswith('filename=') or word.startswith('file='):
                named = word.split('=', 1)[1].strip('`"\'')
            elif FILE.fullmatch(word) and word.lower() not in ('python',):
                named = word
        if not named:
            prefix = text[max(0, match.start()-200):match.start()]
            line = FILENAME_LINE.search(prefix)
            if line:
                named = line.group(1).strip()
        if not named:
            continue
        if named.casefold() in seen:
            raise ValueError('Duplicate file: ' + named)
        _validate(named, content)
        seen.add(named.casefold())
        files.append({'path':named,'content':content})
    return files

def stage_project(files):
    if not isinstance(files, list) or not 2 <= len(files) <= MAX_FILES:
        raise ValueError('Multi-file proposal must contain 2–12 files')
    total = sum(len(x['content'].encode('utf-8')) for x in files)
    if total > MAX_TOTAL:
        raise ValueError('Project edit exceeds 100 KB')
    names = set()
    changes = []
    for f in files:
        name = f['path']
        if name.casefold() in names: raise ValueError('Duplicate path')
        names.add(name.casefold())
        _, old, diff = _validate(name, f['content'])
        changes.append({'path':name,'content':f['content'],'expected_hash':digest(old)})
    proposal_id = uuid.uuid4().hex
    record = {'id':proposal_id,'kind':'project37','created':time.time(),'files':changes}
    with (STORE / (proposal_id+'.json')).open('x',encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False)
    return {'id':proposal_id,'files':[x['path'] for x in changes], 'status':'pending'}

def _load(pid):
    if not isinstance(pid,str) or not VALID_ID.fullmatch(pid):
        raise ValueError('Invalid proposal ID')
    location = STORE / (pid + '.json')
    if not location.is_file():
        raise FileNotFoundError('Proposal missing or processed')
    if time.time() - location.stat().st_mtime > EXPIRY:
        raise ValueError('Proposal expired')
    data = json.loads(location.read_text(encoding='utf-8'))
    if data.get('id') != pid or data.get('kind') != 'project37':
        raise ValueError('Invalid project proposal')
    if not 2 <= len(data.get('files', [])) <= MAX_FILES:
        raise ValueError('Invalid file count')
    return location, data

def _checked(changes):
    snapshot = []
    seen = set()
    for change in changes:
        path, content = change['path'], change['content']
        if path.casefold() in seen: raise ValueError('Duplicate file path')
        seen.add(path.casefold())
        target, current, diff = _validate(path,content)
        if digest(current) != change['expected_hash']:
            raise RuntimeError('File changed after preview: ' + path)
        snapshot.append((target,current,content.encode('utf-8'),diff))
    return snapshot

def preview_project(pid):
    _,record = _load(pid)
    snapshot = _checked(record['files'])
    names = [x['path'] for x in record['files']]
    diff = '\n\n'.join('=== '+name+' ===\n'+entry[3] for name,entry in zip(names,snapshot))
    return {'id':pid, 'path':', '.join(names), 'files':names, 'status':'pending',
            'diff':diff[:60000], 'applied':False}

def apply_project(pid):
    """Serialized, best-effort transactional group write, with rollback and backups.

    This is not an OS-level security boundary or a cross-file atomic transaction.
    """
    lock_path = STORE / 'approval.lock'   # same lock as Agent 3.6
    with lock_path.open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            record_file, record = _load(pid)
            snapshot = _checked(record['files'])
            tmp = {}
            backup_paths = {}
            written = []
            try:
                # Prepare all content before changing any destination.
                for target, old, new, _ in snapshot:
                    if old is not None:
                        backup = target.with_name(target.name+'.'+pid[:8]+'.bak')
                        with backup.open('xb') as out:
                            out.write(old)
                        backup_paths[target] = backup
                    fd, name = tempfile.mkstemp(prefix='.meta37-',suffix='.tmp',dir=target.parent)
                    tmp[target] = name
                    with os.fdopen(fd,'wb') as out:
                        out.write(new);out.flush();os.fsync(out.fileno())
                # Check the complete snapshot again immediately before writing.
                _checked(record['files'])
                for target, old, new, _ in snapshot:
                    os.replace(tmp[target],target)
                    del tmp[target]
                    written.append((target,old))
                record_file.unlink()
                return {'id':pid,'status':'applied','applied':True,
                        'path':', '.join(x['path'] for x in record['files'])}
            except BaseException:
                failures = []
                for target,old in reversed(written):
                    try:
                        if old is None:
                            target.unlink(missing_ok=True)
                        else:
                            # Roll back only files this request had replaced.
                            target.write_bytes(old)
                    except OSError as exc:
                        failures.append(str(exc))
                if failures:
                    raise RuntimeError('Rollback incomplete: '+'; '.join(failures))
                raise
            finally:
                for name in tmp.values():
                    try: os.unlink(name)
                    except FileNotFoundError: pass
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

def maybe_stage_project(task, response, fallback):
    try:
        files = parse_coder_files(response)
        if len(files) < 2:
            return fallback(task,response)
        proposal = stage_project(files)
        lines = ['','### Файловая заявка',
                 '**ID заявки:** '+proposal['id'],
                 '**Статус:** ожидает подтверждения.',
                 '**Файлы:** '+', '.join(proposal['files']),
                 'Изменения не применены. Проверь diff в карточке ниже.']
        return response + '\n'.join(lines)
    except Exception as exc:
        # Preserve full agent output, but do not silently stage invalid proposals.
        return response+'\n\n**Заявка не создана:** '+str(exc)
