"""Collect META sources without changing originals or copying private runtime data."""
import collections
import email.parser
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path

BASE=Path(__file__).resolve().parent
DEST=BASE/'META_Collected'
ROOTS=[Path('D:/'),Path.home()/'Downloads']
SKIP={'.git','.venv','venv','node_modules','__pycache__','$RECYCLE.BIN','System Volume Information'}
PRIVATE={'data','memory','meta40_state','meta40_receipts','pending_changes','.aws','.ssh','.codex','.agents'}
TEXT={'.py','.ps1','.cmd','.bat','.md','.txt','.json','.js','.ts','.tsx','.jsx','.html','.css','.yml','.yaml','.toml','.ini','.cfg','.csv','.svg','.bak'}
BINARY={'.png','.ico','.exe','.docx','.pdf'}
KNOWN_SECRETS=set()
SECRET_PATTERNS=[
    re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}\b'),
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}\b'),
    re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|refresh[_-]?token)\s*[=:]\s*[\x22\x27]([A-Za-z0-9_./+=-]{20,})[\x22\x27]'),
]
inventory=[];included=[];errors=[];found_roots=[];scan_counts=collections.Counter()


def linked(p):
    try:return p.is_symlink() or bool(getattr(p.lstat(),'st_file_attributes',0)&0x400)
    except OSError:return True


def sha(data):return hashlib.sha256(data).hexdigest()


def jsonwrite(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def discover():
    # Inventory names across D and Downloads; never follow links or traverse
    # application environments. No unrelated file content is collected.
    for root in ROOTS:
        for folder,dirs,files in os.walk(root,followlinks=False,onerror=lambda e:errors.append({'path':e.filename,'error':type(e).__name__})):
            scan_counts['directories']+=1
            p=Path(folder)
            dirs[:]=[d for d in dirs if d not in SKIP and not linked(p/d)]
            scan_counts['files']+=len(files)
            if re.match(r'^META(?:$|[_ .-])',p.name,re.I):
                if not any(p.is_relative_to(old) for old in found_roots):found_roots.append(p)
    return found_roots


def learn_secrets():
    for root in found_roots:
        for folder,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if d not in SKIP and d.casefold() not in PRIVATE and not linked(Path(folder)/d)]
            for name in files:
                if name=='meta40_config.json':
                    path=Path(folder)/name
                    try:
                        data=json.loads(path.read_text(encoding='utf-8-sig'))
                        for k,v in data.items():
                            if re.search('token|secret|password|key',k,re.I) and isinstance(v,str) and len(v)>=8:KNOWN_SECRETS.add(v)
                    except (OSError,ValueError):pass


def clean(raw):
    value=raw.decode('utf-8-sig')
    changed=False
    for secret in KNOWN_SECRETS:
        if secret in value:value=value.replace(secret,'REDACTED_LOCAL_SECRET');changed=True
    for pattern in SECRET_PATTERNS:
        def mask(match):
            nonlocal changed
            changed=True
            if match.lastindex:
                return match.group().replace(match.group(1),'REDACTED_LOCAL_SECRET')
            return 'REDACTED_LOCAL_SECRET'
        value=pattern.sub(mask,value)
    return (value.encode('utf-8') if changed else raw),changed


def unsafe_archive(raw):
    try:
        import io
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if len(z.infolist())>10000:return True
            for entry in z.infolist():
                if entry.is_dir():continue
                parts={p.casefold() for p in Path(entry.filename).parts}
                if parts&PRIVATE or Path(entry.filename).suffix.lower() in {'.db','.sqlite','.sqlite3','.env','.pem','.key'}:return True
                if entry.file_size>10_000_000:return True
                payload=z.read(entry)
                if any(s.encode() in payload for s in KNOWN_SECRETS):return True
                try:
                    _,modified=clean(payload)
                    if modified:return True
                except UnicodeError:pass
        return False
    except (ValueError,OSError,zipfile.BadZipFile):return True


def copy_file(path,relative,source_label):
    record={'source':str(path),'destination':relative.as_posix()}
    try:
        size=path.stat().st_size;record['bytes']=size
        parts={p.casefold() for p in path.parts}
        name=path.name.lower();suffix=path.suffix.lower()
        reason=None
        if linked(path):reason='link_or_junction'
        elif parts & PRIVATE:reason='private_runtime_data'
        elif any(p in SKIP for p in path.parts):reason='environment_or_cache'
        elif 'blobs' in parts and 'models' in parts:reason='model_weights'
        elif name=='meta40_config.json':reason='live_auth_config'
        elif name.startswith('.env') or suffix in {'.db','.sqlite','.sqlite3','.log','.lock','.pem','.key','.pfx','.p12'}:reason='private_or_runtime_file'
        elif name in {'manifest.json','sha256sums.txt'} and any('backup' in p.lower() for p in path.parts):reason='local_rollback_manifest'
        elif size>20_000_000:reason='large_binary'
        if reason:
            record['status']='excluded';record['reason']=reason;inventory.append(record);return
        raw=path.read_bytes()
        if len(raw)!=size:raise OSError('Source changed size during collection')
        modified=False
        if suffix=='.zip' or suffix=='.docx':
            if unsafe_archive(raw):reason='archive_contains_private_or_unchecked_data'
        elif suffix in TEXT or name=='modelfile' or '.backup_' in name or ('models' in parts and suffix==''):
            try:raw,modified=clean(raw)
            except UnicodeError:reason='non_text_backup_or_source'
        elif suffix not in BINARY and not name.endswith('.sha256'):
            reason='unrecognized_generated_file'
        if reason:
            record.update(status='excluded',reason=reason);inventory.append(record);return
        target=DEST/relative
        if target.exists():raise ValueError('Destination collision: '+relative.as_posix())
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        record.update(status='included_redacted' if modified else 'included',sha256=sha(raw))
        inventory.append(record)
        included.append({'path':relative.as_posix(),'source_group':source_label,'sha256':sha(raw),'bytes':len(raw),'redacted':modified})
    except (OSError,ValueError) as exc:
        record.update(status='error',reason=str(exc));inventory.append(record)


def group(root):
    if root==Path('D:/META'):return Path('installed_meta'), 'installed_meta'
    if root.name=='META_1_3_Hotfix':return Path('desktop'), 'desktop'
    return Path('downloads')/root.name, 'downloads/'+root.name


def collect_root(root,prefix,label):
    for folder,dirs,files in os.walk(root,followlinks=False,onerror=lambda e:errors.append({'path':e.filename,'error':type(e).__name__})):
        parent=Path(folder)
        # Environments contain no project source. Model weights are counted by
        # their filenames and sizes but never read into memory.
        for excluded in list(dirs):
            if excluded in SKIP or linked(parent/excluded):
                inventory.append({'source':str(parent/excluded),'status':'excluded_directory','reason':'environment_cache_or_link'})
        dirs[:]=[d for d in dirs if d not in SKIP and not linked(parent/d)]
        for name in files:
            relative=(parent/name).relative_to(root)
            copy_file(parent/name,prefix/relative,label)


def main():
    if DEST.exists():raise SystemExit('Collection folder already exists; choose a new destination before collecting again')
    discover();learn_secrets();DEST.mkdir()
    for root in found_roots:
        prefix,label=group(root);collect_root(root,prefix,label)
    collect_root(BASE/'META_4_0',Path('releases/meta40_upgrade'),'meta40_upgrade')
    for p in BASE.glob('META*.docx'):copy_file(p,Path('docs')/p.name,'chat_document')
    for p in BASE.glob('META*.zip'):copy_file(p,Path('archives')/p.name,'chat_release')
    for p in (Path.home()/'Downloads').glob('META*.zip'):copy_file(p,Path('archives/downloads')/p.name,'download_release')
    # Capture dependency versions by reading metadata, without importing the
    # application or executing its tests or startup hooks.
    site=Path('D:/META/Core/.venv/Lib/site-packages')
    deps=[]
    for meta in site.glob('*.dist-info/METADATA'):
        msg=email.parser.Parser().parsestr(meta.read_text(encoding='utf-8',errors='replace'),headersonly=True)
        if msg.get('Name') and msg.get('Version'):deps.append(msg['Name']+'=='+msg['Version'])
    (DEST/'requirements.local-snapshot.txt').write_text('\n'.join(sorted(set(deps),key=str.casefold))+'\n',encoding='utf-8')
    example={'version':'4.0.1','projects':r'D:\META\Projects','token':'GENERATE_A_NEW_LOCAL_TOKEN'}
    jsonwrite(DEST/'installed_meta/Core/meta40_config.example.json',example)
    jsonwrite(DEST/'SOURCE_INDEX.json',included)
    summary={'scanned_roots':[str(p) for p in ROOTS],'scan_counts':dict(scan_counts),
             'meta_source_roots':[str(p) for p in found_roots],
             'included_files':len(included),'included_bytes':sum(p['bytes'] for p in included),
             'redacted_files':sum(p['redacted'] for p in included),
             'status_counts':dict(collections.Counter(r['status'] for r in inventory)),
             'excluded_bytes':sum(r.get('bytes',0) for r in inventory if r['status']=='excluded'),
             'walk_errors':errors,'files':inventory}
    jsonwrite(BASE/'META_Collection_Inventory.local.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='files'},ensure_ascii=True,indent=2))


if __name__=='__main__':main()
