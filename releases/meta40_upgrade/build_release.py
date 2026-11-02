"""Package source release, excluding caches; verify every archived byte."""
import hashlib
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent
files = sorted(p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts
               and p.name != 'SHA256SUMS.txt' and p.suffix not in {'.pyc','.zip'})
hashes = '\n'.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(root).as_posix() for p in files)+'\n'
(root/'SHA256SUMS.txt').write_text(hashes,encoding='utf-8')
files.append(root/'SHA256SUMS.txt')
destination = root.parent/'META_4_0_Upgrade.zip'
with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED) as archive:
    for p in files:
        archive.write(p,'META_4_0/'+p.relative_to(root).as_posix())
with zipfile.ZipFile(destination) as archive:
    assert archive.testzip() is None
    for p in files:
        assert archive.read('META_4_0/'+p.relative_to(root).as_posix()) == p.read_bytes()
digest = hashlib.sha256(destination.read_bytes()).hexdigest()
destination.with_suffix('.zip.sha256').write_text(digest+'  '+destination.name+'\n',encoding='ascii')
print(str(destination))
print(str(len(files))+' files; '+str(destination.stat().st_size)+' bytes; SHA256 '+digest)
