"""Plan/apply Core-only update to an existing installation with strict drift checks."""
import argparse,hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
repo=Path(__file__).resolve().parents[2]
runtime=Path('C:/Users/Desktop/META_FULL_DESKTOP/META-Next')
core=runtime/'_internal/core'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def normalized(value):return value.decode('utf-8-sig').replace('\r\n','\n')
def prior(relative):
    try:return subprocess.check_output(['git','show','phase10-complete:studio/core/'+relative],cwd=repo,stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:return None
def expected(relative):
    data=prior(relative)
    if relative in ('meta5/transport.py','meta5/performance.py','config/performance.json'):
        return subprocess.check_output(['git','show','5574e62:studio/core/'+relative],cwd=repo)
    if relative=='meta5/dialogue.py':
        old="        understanding=await asyncio.to_thread(normalize,last,'\\n'.join(users[-8:]),parse_local)"
        new="        from .performance import simple_turn\n        parser=None if simple_turn(last) else parse_local\n        understanding=await asyncio.to_thread(normalize,last,'\\n'.join(users[-8:]),parser)"
        return normalized(data).replace(old,new).encode()
    return data

def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.phase11-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def run(apply=False):
    if not (runtime/'META-Next.exe').is_file() or not core.is_dir():raise ValueError('Existing project installation required')
    names=subprocess.check_output(['git','ls-files','studio/core'],cwd=repo).decode().splitlines()
    plan=[];unknown=[]
    for name in names:
        relative=Path(name).relative_to('studio/core').as_posix()
        if not (relative.startswith('meta5/') or relative.startswith('config/')):continue
        if Path(relative).suffix not in ('.py','.json','.md'):continue
        source=repo/name;target=core/relative
        if target.exists() and normalized(target.read_bytes())==normalized(source.read_bytes()):continue
        before=expected(relative)
        if target.exists() and (before is None or normalized(target.read_bytes())!=normalized(before)):
            unknown.append(relative);continue
        if source.suffix=='.py':compile(source.read_text('utf-8'),str(source),'exec')
        elif source.suffix=='.json':json.loads(source.read_text('utf-8'))
        plan.append({'relative':relative,'bytes':source.stat().st_size,'sha256':sha(source),'previous_sha256':sha(target) if target.exists() else None})
    report={'applied':False,'runtime':str(runtime),'files':plan,'unknown_local_changes':unknown,'preserves':'EXE/frontend/shortcuts/Preview/venv/models/secrets and performance settings'}
    if unknown:return report
    if apply:
        # Do not replace modules underneath a live shell/Core.
        check=subprocess.check_output(['powershell','-NoProfile','-Command',"@(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq '"+str(runtime/'META-Next.exe')+"' }).Count"],text=True).strip()
        if check!='0':raise RuntimeError('Working META is running; Core update requires a clean restart')
        protected=[runtime/'META-Next.exe',*sorted((runtime/'_internal/frontend').rglob('*')),Path('C:/Users/Desktop/META-Next.lnk')]
        hashes={str(p):sha(p) for p in protected if p.is_file()}
        for row in plan:atomic(core/row['relative'],(repo/'studio/core'/row['relative']).read_bytes())
        if any(sha(Path(p))!=h for p,h in hashes.items()):raise RuntimeError('Protected shell hash changed')
        report.update(applied=True,protected_unchanged=len(hashes))
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    report=run(args.apply);folder=repo/'build/phase11-deployment';folder.mkdir(parents=True,exist_ok=True)
    (folder/('applied.json' if args.apply else 'plan.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));sys.exit(1 if report['unknown_local_changes'] else 0)
