import json,secrets
from pathlib import Path
root=Path(__file__).resolve().parent
config=root/'meta40_config.json'
if config.exists():
    print('Existing local configuration preserved')
else:
    projects=Path(r'D:\META\Projects')
    if not projects.is_dir():raise SystemExit('Project directory must already exist: '+str(projects))
    with config.open('x',encoding='utf-8') as f:json.dump({'token':secrets.token_urlsafe(48),'projects':str(projects)},f,indent=2)
    print('Local configuration created; do not publish it')
