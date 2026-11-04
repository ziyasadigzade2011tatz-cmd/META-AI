import hashlib
from pathlib import Path
import subprocess
import zipfile

repo=Path(__file__).resolve().parents[2];runtime=repo/'build/META-Next';payload=repo/'build/payload.zip';output=repo/'dist/META-Setup.exe';output.parent.mkdir(exist_ok=True)
lines=[]
with zipfile.ZipFile(payload,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for file in sorted(runtime.rglob('*')):
        if not file.is_file() or '__pycache__' in file.parts:continue
        relative=file.relative_to(runtime).as_posix()
        if file.suffix in ('.sqlite','.db') or file.name in ('meta40_config.json','preferences.json'):raise ValueError('Private runtime file in installer: '+relative)
        raw=file.read_bytes();lines.append(hashlib.sha256(raw).hexdigest()+'  '+relative);archive.writestr(relative,raw)
    archive.writestr('payload.sha256','\n'.join(lines)+'\n')
with zipfile.ZipFile(payload) as archive:
    if archive.testzip():raise ValueError('ZIP CRC failed')
csc=Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
subprocess.run([str(csc),'/nologo','/utf8output','/codepage:65001','/target:winexe','/platform:x64','/optimize+','/out:'+str(output),
 '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll',
 '/resource:'+str(payload)+',META.Payload.zip',str(repo/'studio/build_tools/Installer.cs')],check=True)
print('Installer: '+str(output)+' bytes='+str(output.stat().st_size)+' sha256='+hashlib.sha256(output.read_bytes()).hexdigest())
