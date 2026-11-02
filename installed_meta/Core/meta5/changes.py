"""Multi-operation review and recovery, sharing agent_pending's approval lock."""
import base64
import difflib
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from .project import Project,digest,validate
from .storage import atomic_json,STATE


def store():
    import agent_pending
    return agent_pending.STORE
def ident(pid):
    if not isinstance(pid,str) or not re.fullmatch('[a-f0-9]{32}',pid):raise ValueError('Неверный ID заявки')
    return pid
def ours(pid):
    from .storage import read_json
    return (read_json(store()/(ident(pid)+'.json'),{}) or {}).get('kind')=='meta5'
def boundary(root):
    from agent_tools import WORKSPACE
    p=Project(root)
    if not p.root.is_relative_to(Path(WORKSPACE).resolve()):raise ValueError('Изменения только внутри Projects')
    return p


def stage(root,edits,expected):
    project=boundary(root)
    if not 1<=len(edits)<=50 or sum(len(v.encode()) for v in edits.values() if v is not None)>2_000_000:raise ValueError('Лимит заявки: 50 файлов / 2 МБ')
    if len({n.casefold() for n in edits})!=len(edits):raise ValueError('Дубли путей Windows')
    files=[]
    for name,content in edits.items():
        p=project.path(name);old=p.read_bytes() if p.exists() else None
        if digest(old)!=expected.get(name):raise ValueError('Исходник изменился после начала задачи: '+name)
        if content is not None:validate(name,content)
        if old==(content.encode('utf-8') if content is not None else None):continue
        files.append({'path':name,'content':content,'expected_hash':digest(old)})
    if not files:return None
    pid=uuid.uuid4().hex
    atomic_json(store()/(pid+'.json'),{'id':pid,'kind':'meta5','created':time.time(),'root':str(project.root),'files':files})
    return {'id':pid,'status':'pending','files':[f['path'] for f in files],'applied':False}


def load(pid,check=True):
    location=store()/(ident(pid)+'.json');record=json.loads(location.read_text(encoding='utf-8'))
    if record.get('id')!=pid or record.get('kind')!='meta5':raise ValueError('Неверная заявка')
    if time.time()-record['created']>86400:raise ValueError('Заявка устарела')
    project=boundary(record['root']);files=record['files']
    if not 1<=len(files)<=50 or len({f['path'].casefold() for f in files})!=len(files):raise ValueError('Неверный набор файлов')
    if sum(len(f['content'].encode()) for f in files if f['content'] is not None)>2_000_000:raise ValueError('Заявка слишком большая')
    checked=[]
    for f in files:
        p=project.path(f['path']);content=f['content']
        if content is not None:validate(f['path'],content)
        old=p.read_bytes() if p.exists() else None
        if check and digest(old)!=f['expected_hash']:raise ValueError('Файл изменён после предпросмотра: '+f['path'])
        checked.append((p,old,content.encode('utf-8') if content is not None else None))
    return location,record,checked


def preview(pid):
    _,record,checked=load(pid);diff=[]
    for f,(_,old,new) in zip(record['files'],checked):
        diff.append(''.join(difflib.unified_diff((old or b'').decode('utf-8-sig').splitlines(True),(new or b'').decode('utf-8-sig').splitlines(True),fromfile='before/'+f['path'],tofile='after/'+f['path'])))
    return {'id':pid,'status':'pending','files':[f['path'] for f in record['files']],
            'path':', '.join(f['path'] for f in record['files']),'diff':'\n'.join(diff),'applied':False}


def replace(path,raw):
    from meta40.proposals import replace_bytes
    if raw is None:path.unlink(missing_ok=True)
    else:path.parent.mkdir(parents=True,exist_ok=True);replace_bytes(path,raw)


def approve(pid):
    from meta40.proposals import approval_lock
    with approval_lock():
        location,record,checked=load(pid)
        receipt=store()/'meta5_receipts'/(pid+'.json')
        if receipt.exists():raise ValueError('Сначала проверь квитанцию прежней попытки')
        journal={'id':pid,'root':record['root'],'status':'applying','files':[{'path':f['path'],'old':base64.b64encode(old).decode() if old is not None else None,'new_hash':digest(new)} for f,(_,old,new) in zip(record['files'],checked)]}
        atomic_json(receipt,journal);written=[]
        try:
            load(pid)
            for target,old,new in checked:
                replace(target,new);written.append((target,old))
            journal['status']='applied';atomic_json(receipt,journal);location.unlink()
            return {'id':pid,'status':'applied','applied':True,'rollback_receipt':str(receipt)}
        except BaseException:
            errors=[]
            for target,old in reversed(written):
                try:replace(target,old)
                except OSError as exc:errors.append(str(exc))
            journal.update(status='rollback_incomplete' if errors else 'rolled_back',errors=errors);atomic_json(receipt,journal);raise


def rollback(pid):
    from meta40.proposals import approval_lock
    with approval_lock():
        location=store()/'meta5_receipts'/(ident(pid)+'.json');record=json.loads(location.read_text(encoding='utf-8'));project=boundary(record['root']);checked=[]
        for f in record['files']:
            p=project.path(f['path']);old=base64.b64decode(f['old'],validate=True) if f['old'] is not None else None
            current=p.read_bytes() if p.exists() else None
            if digest(current) not in (digest(old),f['new_hash']):raise ValueError('Более поздние правки: '+f['path'])
            checked.append((p,old))
        for p,old in checked:replace(p,old)
        record['status']='rolled_back';atomic_json(location,record);return {'status':'rolled_back','id':pid}


if __name__=='__main__':
    import sys
    if len(sys.argv)!=3 or sys.argv[1]!='rollback':raise SystemExit('Usage: python -m meta5.changes rollback PROPOSAL_ID')
    print(rollback(sys.argv[2]))
