import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
base={(e['area'],e['path']):e['sha256'] for e in json.loads((ROOT/'baseline.json').read_text(encoding='utf-8'))}
entries=[]
for area in ('core','desktop'):
    root=ROOT/'candidate'/area
    for file in sorted(root.rglob('*')):
        if not file.is_file():continue
        name=file.relative_to(root).as_posix()
        if '__pycache__' in file.parts or 'meta5_state' in file.parts:continue
        if file.suffix not in ('.py','.cjs','.js','.css','.html') and name not in ('meta5_tools.json','meta5_models_seed.json'):continue
        old=base.get((area,name));new=hashlib.sha256(file.read_bytes()).hexdigest()
        if old!=new:entries.append({'area':area,'path':name,'old_hash':old,'new_hash':new})
(ROOT/'upgrade_manifest.json').write_text(json.dumps(entries,indent=2),encoding='utf-8')
print('Upgrade files:',len(entries))
