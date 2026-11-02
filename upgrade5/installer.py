"""Hash-checked META upgrade and rollback. Never creates the project/Core roots."""
import argparse,hashlib,json,os,sys,tempfile
from datetime import datetime
from pathlib import Path
HERE=Path(__file__).resolve().parent
def sha(raw):return hashlib.sha256(raw).hexdigest() if raw is not None else None
def read(path):return path.read_bytes() if path.is_file() else None
def save(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.meta5-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
def json_save(path,data):save(path,json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8'))
def checked(root,name):
    root=Path(root).resolve();relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('Invalid manifest path')
    target=root/relative
    if not target.resolve().is_relative_to(root):raise ValueError('Path escapes installation root')
    for part in [target,*target.parents]:
        if part==root:break
        if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):raise ValueError('Linked installation path rejected')
    return target
def roots(core,desktop):
    result={'core':Path(core).resolve(),'desktop':Path(desktop).resolve()}
    for area,marker in [('core','main.py'),('desktop','meta_desktop.py')]:
        if not result[area].is_dir() or not (result[area]/marker).is_file():raise ValueError('Existing '+area+' directory is required: '+str(result[area]))
    return result
def manifest():return json.loads((HERE/'upgrade_manifest.json').read_text(encoding='utf-8'))
def preflight(destinations):
    entries=manifest();errors=[]
    for item in entries:
        source=checked(HERE/'candidate'/item['area'],item['path']);target=checked(destinations[item['area']],item['path'])
        if sha(read(source))!=item['new_hash']:errors.append('Package damaged: '+item['path'])
        actual=sha(read(target))
        if actual not in (item['old_hash'],item['new_hash']):errors.append('Source changed since snapshot: '+str(target))
    if errors:raise ValueError('\n'.join(errors))
    return [i for i in entries if sha(read(checked(destinations[i['area']],i['path'])))!=i['new_hash']]
def install(destinations):
    entries=preflight(destinations)
    if not entries:return {'already_installed':True}
    backup=destinations['core']/'upgrade_backups'/('META5_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir(parents=True)
    receipt={'version':'5.0.0','roots':{k:str(v) for k,v in destinations.items()},'entries':entries,'status':'prepared'}
    for item in entries:
        raw=read(checked(destinations[item['area']],item['path']))
        if raw is not None:save(checked(backup/item['area'],item['path']),raw)
    json_save(backup/'receipt.json',receipt)
    written=[]
    try:
        for item in entries:
            target=checked(destinations[item['area']],item['path'])
            if sha(read(target))!=item['old_hash']:raise ValueError('Concurrent modification: '+str(target))
            save(target,checked(HERE/'candidate'/item['area'],item['path']).read_bytes());written.append(item)
        receipt['status']='installed';json_save(backup/'receipt.json',receipt)
        json_save(HERE/'install-last.json',{'backup':str(backup)})
        return {'installed_files':len(entries),'backup':str(backup)}
    except Exception:
        for item in reversed(written):
            target=checked(destinations[item['area']],item['path']);original=read(checked(backup/item['area'],item['path']))
            if original is None:target.unlink(missing_ok=True)
            else:save(target,original)
        receipt['status']='install_failed_restored';json_save(backup/'receipt.json',receipt);raise
def rollback(backup):
    backup=Path(backup).resolve();receipt=json.loads((backup/'receipt.json').read_text(encoding='utf-8'))
    destinations=roots(receipt['roots']['core'],receipt['roots']['desktop']);entries=receipt['entries']
    if backup.parent!=destinations['core']/'upgrade_backups':raise ValueError('Backup must belong to the installed Core')
    for item in entries:
        if sha(read(checked(destinations[item['area']],item['path']))) not in (item['new_hash'],item['old_hash']):raise ValueError('File modified after upgrade; rollback stopped: '+item['path'])
        if sha(read(checked(backup/item['area'],item['path'])))!=item['old_hash']:raise ValueError('Backup damaged: '+item['path'])
    for item in reversed(entries):
        target=checked(destinations[item['area']],item['path']);raw=read(checked(backup/item['area'],item['path']))
        if raw is None:target.unlink(missing_ok=True)
        else:save(target,raw)
    receipt['status']='rolled_back';json_save(backup/'receipt.json',receipt)
    return {'rolled_back':True,'backup':str(backup)}
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['check','install','rollback']);p.add_argument('--core',default=r'D:\META\Core');p.add_argument('--desktop',default=r'C:\Users\user\Downloads\META_1_3_Hotfix');p.add_argument('--backup')
    args=p.parse_args()
    if args.action=='rollback':result=rollback(args.backup or json.loads((HERE/'install-last.json').read_text(encoding='utf-8'))['backup'])
    else:
        destinations=roots(args.core,args.desktop)
        result={'ready':True,'files':len(preflight(destinations))} if args.action=='check' else install(destinations)
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
    try:main()
    except Exception as exc:print('META upgrade stopped: '+str(exc),file=sys.stderr);sys.exit(1)
