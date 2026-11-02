"""Apply the project-folder fix to an existing META 4.0 installation."""
import argparse
import ast
import json
from datetime import datetime
from pathlib import Path
from install_meta40 import HERE, checked_target, sha, text, write


def apply(core, desktop, check=False):
    roots={'core':core.resolve(),'desktop':desktop.resolve()}
    core,desktop=roots['core'],roots['desktop']
    if '# META40_CORE_INTEGRATION' not in text(core/'main.py'):
        raise ValueError('Existing META 4.0 installation required')
    js=text(desktop/'assets/app.js')
    begin='// META40_UI_BEGIN';end='// META40_UI_END'
    if js.count(begin)!=1 or js.count(end)!=1:
        raise ValueError('Ambiguous META 4.0 UI markers; files unchanged')
    start=js.index(begin);stop=js.index(end)+len(end)
    updated=js[:start]+text(HERE/'desktop/agent40.js').strip()+js[stop:]
    files={('desktop','assets/app.js'):updated.encode('utf-8')}
    for name in ('__init__.py','workspace.py','api.py'):
        raw=(HERE/'core/meta40'/name).read_bytes()
        ast.parse(raw.decode('utf-8'))
        files['core','meta40/'+name]=raw
    prepared=[]
    for (area,name),raw in files.items():
        target=checked_target(roots,area,name)
        old=target.read_bytes()
        if old!=raw:prepared.append((area,name,target,old,raw))
    if check or not prepared:
        print('META 4.0.1 patch: '+str(len(prepared))+' files to update; no changes written.')
        return
    backup=core/'meta40_backups'/('fix401_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir(parents=True)
    manifest={'version':'4.0.1','status':'prepared','roots':{k:str(v) for k,v in roots.items()},'files':[]}
    for i,(area,name,target,old,raw) in enumerate(prepared):
        location=str(i)+'.bak';write(backup/location,old)
        manifest['files'].append({'area':area,'path':name,'backup':location,
                                 'before_hash':sha(old),'installed_hash':sha(raw)})
    path=backup/'manifest.json'
    write(path,json.dumps(manifest,indent=2).encode())
    written=[]
    try:
        for area,name,target,old,raw in prepared:
            if target.read_bytes()!=old:raise RuntimeError('File changed during patch: '+str(target))
            write(target,raw);written.append((target,old))
        manifest['status']='installed'
        write(path,json.dumps(manifest,indent=2).encode())
    except BaseException:
        errors=[]
        for target,old in reversed(written):
            try:write(target,old)
            except OSError as exc:errors.append(str(exc))
        manifest.update(status='rollback_incomplete' if errors else 'rolled_back',errors=errors)
        write(path,json.dumps(manifest,indent=2).encode())
        raise
    print('META 4.0.1 applied. Restart Core and Desktop.')
    print('Rollback manifest: '+str(path))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core',type=Path,default=Path(r'D:\META\Core'))
    parser.add_argument('--desktop',type=Path,default=Path.home()/'Downloads/META_1_3_Hotfix')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    apply(args.core,args.desktop,args.check)
