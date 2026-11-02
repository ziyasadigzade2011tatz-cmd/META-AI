"""Safe installer for META 4.4 web bridge; install and rollback using a backup."""
from pathlib import Path
import ast
import hashlib
import shutil
import sys
import json
from datetime import datetime

TAG = '# META_4_4_CHAT_WEB_BRIDGE'
HOOK = '\n\n'+TAG+' -- preserves existing agent_chat handler\nfrom meta_web_bridge import WebChatMiddleware\napp.add_middleware(WebChatMiddleware)\n'

def main():
    core = Path(sys.argv[1] if len(sys.argv)>1 else r'D:\META\Core').resolve()
    source = Path(__file__).with_name('meta_web_bridge.py')
    main_file = core/'main.py'
    target = core/'meta_web_bridge.py'
    if not main_file.is_file() or not (core/'meta40'/'web_research.py').is_file():
        raise SystemExit('Missing main.py or meta40/web_research.py in '+str(core))
    before = main_file.read_bytes()
    text = before.decode('utf-8-sig')
    if TAG in text:
        raise SystemExit('Web bridge already installed; no changes made')
    if target.exists():
        raise SystemExit('meta_web_bridge.py already exists: inspect it first')
    if 'install_meta40(app)' not in text or 'agent_completions' not in text:
        raise SystemExit('Unknown META main.py structure; refusing to patch')
    candidate = text+HOOK
    ast.parse(candidate)
    ast.parse(source.read_text(encoding='utf-8'))
    backup = core/'meta_web44_backups'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup.mkdir(parents=True,exist_ok=False)
    (backup/'main.py').write_bytes(before)
    manifest={'main_sha256_before':hashlib.sha256(before).hexdigest(),
              'main_sha256_after':hashlib.sha256(candidate.encode()).hexdigest(),
              'bridge_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    try:
        shutil.copyfile(source,target)
        main_file.write_bytes(candidate.encode('utf-8'))
    except Exception:
        main_file.write_bytes(before)
        if target.exists(): target.unlink()
        raise
    print('INSTALLED META Web 4.4. Backup:',backup)
    print('Restart META Core and Desktop.')

if __name__=='__main__': main()
