"""Build a new runtime from the installed Full dependency bundle, without user data."""
import argparse
import json
import marshal
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zlib
from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.archive.writers import CArchiveWriter

parser=argparse.ArgumentParser();parser.add_argument('--base',required=True);parser.add_argument('--out',required=True);parser.add_argument('--refresh',action='store_true');parser.add_argument('--update-code',action='store_true');args=parser.parse_args()
source=Path(args.base).resolve();out=Path(args.out).resolve();studio=Path(__file__).resolve().parents[1]
if sys.version_info[:2]!=(3,15):raise SystemExit('This base runtime requires Python 3.15 bytecode')
if out==source or source in out.parents or out in source.parents:raise SystemExit('Build must be outside the installed application')
if out.exists():
    generated=studio.parent/'build'
    if not (args.refresh or args.update_code) or not out.is_relative_to(generated.resolve()) or out.name!='META-Next':raise SystemExit('Refusing to replace non-generated output')
    if not args.update_code:shutil.rmtree(out)
out.mkdir(parents=True,exist_ok=args.update_code)
def dependencies_only(folder,names):
    skipped=set(shutil.ignore_patterns('__pycache__','*.log')(folder,names))
    if Path(folder).resolve()==(source/'_internal').resolve():skipped.update({'core','frontend'})
    return skipped
if not args.update_code:shutil.copytree(source/'_internal',out/'_internal',ignore=dependencies_only)
# The dependency bundle is retained; source and frontend are the current build inputs.
target=out/'_internal/core'
if target.exists() and not args.update_code:shutil.rmtree(target)
shutil.copytree(studio/'core',target,dirs_exist_ok=args.update_code,ignore=shutil.ignore_patterns('__pycache__','*_state','*.sqlite*','*.db','meta40_config.json'))
frontend=out/'_internal/frontend/dist'
if frontend.exists() and not args.update_code:shutil.rmtree(frontend)
shutil.copytree(studio/'frontend/dist',frontend,dirs_exist_ok=args.update_code)
native=out/'_internal/native';native.mkdir(exist_ok=True)
subprocess.run([r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe','/nologo','/utf8output','/codepage:65001','/target:exe','/platform:x64','/optimize+',
    '/out:'+str(native/'Meta.DesktopBridge.exe'),'/reference:System.Drawing.dll','/reference:System.Web.Extensions.dll',str(studio/'native/DesktopBridge.cs')],check=True)
sources=out/'_internal/source'
import unittest
test_support=out/'_internal/test_support';test_support.mkdir(exist_ok=True)
shutil.copytree(Path(unittest.__file__).parent,test_support/'unittest',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
license_path=Path(sys.base_prefix)/'LICENSE.txt'
if license_path.is_file():shutil.copy2(license_path,test_support/'PYTHON_LICENSE.txt')
for group in ('frontend','tests','native'):
    folder=sources/group;folder.mkdir(parents=True,exist_ok=True)
    allowed={'src.ts','activity.js','extensions.ts','contracts.ts','tsconfig.json','index.html','style.css','package.json','package-lock.json'}
    for file in (studio/group).iterdir():
        if file.is_file() and ((group=='frontend' and file.name in allowed) or (group=='tests' and file.suffix in ('.py','.json')) or (group=='native' and file.suffix=='.cs')):shutil.copy2(file,folder/file.name)
shutil.copy2(studio/'build_tools/desktop_base.bin',out/'_internal/studio_base.bin')
reader=CArchiveReader(str(source/'META-Next.exe'))
raw=(source/'META-Next.exe').read_bytes();start=reader._start_offset
code=marshal.dumps(compile((studio/'build_tools/entry.py').read_text(encoding='utf-8'),'app.py','exec'))
chunks=[];toc=[];offset=0
for name,entry in reader.toc.items():
    pos,packed,unpacked,compressed,kind=entry
    data=code if name=='app' else reader.extract(name)
    stored=zlib.compress(data,9) if compressed else data
    chunks.append(stored);toc.append((offset,len(stored),len(data),compressed,kind,name));offset+=len(stored)
for option in reader.options:toc.append((offset,0,0,0,'o',option))
toc_raw=CArchiveWriter._serialize_toc(toc)
length=offset+len(toc_raw)+CArchiveWriter._COOKIE_LENGTH
cookie=struct.pack(CArchiveWriter._COOKIE_FORMAT,CArchiveWriter._COOKIE_MAGIC_PATTERN,length,offset,len(toc_raw),315,b'python315.dll')
(out/'META-Next.exe').write_bytes(raw[:start]+b''.join(chunks)+toc_raw+cookie)
(out/'VERSION.txt').write_text(json.loads((studio/'frontend/package.json').read_text('utf-8'))['version']+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'output':str(out),'files':sum(1 for p in out.rglob('*') if p.is_file())}))
