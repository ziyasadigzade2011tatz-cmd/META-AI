"""Install META 4.0 over the inspected Core 3.6–3.8 / Desktop 1.3 contracts."""
import argparse
import ast
import hashlib
import json
import os
import secrets
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE_MARK = '# META40_CORE_INTEGRATION'
PENDING_MARK = '# META40_PENDING_INTEGRATION'
DESKTOP_MARK = '# META40_DESKTOP_INTEGRATION'
PENDING_PATCH = '''
# META40_PENDING_INTEGRATION
_meta40_previous_preview = proposal_preview
_meta40_previous_approve = proposal_approve

def proposal_preview(proposal_id):
    from meta40.proposals import is_ours, preview
    return preview(proposal_id) if is_ours(proposal_id) else _meta40_previous_preview(proposal_id)

def proposal_approve(proposal_id):
    from meta40.proposals import is_ours, approve
    return approve(proposal_id) if is_ours(proposal_id) else _meta40_previous_approve(proposal_id)
'''


def sha(raw): return hashlib.sha256(raw).hexdigest() if raw is not None else None


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.meta40-install-')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def text(path): return path.read_text(encoding='utf-8-sig')


def replacements(core, desktop, projects):
    main = text(core/'main.py')
    pending = text(core/'agent_pending.py')
    ui = text(desktop/'meta_desktop.py')
    js = text(desktop/'assets/app.js')
    if CORE_MARK in main or PENDING_MARK in pending or DESKTOP_MARK in ui:
        raise ValueError('META 4.0 already present or partially installed. Use its rollback manifest first.')
    for token in ('app = FastAPI(',):
        if token not in main: raise ValueError('Unsupported main.py contract: '+token)
    for token in ('def proposal_preview(', 'def proposal_approve(', 'def proposal_reject('):
        if token not in pending: raise ValueError('Unsupported agent_pending contract: '+token)
    for token in ('def authorized(', 'def do_GET(', 'def do_POST(', 'def account_state(', 'CORE_URL ='):
        if token not in ui: raise ValueError('Unsupported Desktop contract: '+token)
    get = '    def do_GET(self):\n'
    post = '    def do_POST(self):\n'
    for hook in (get, post):
        if ui.count(hook) != 1: raise ValueError('Ambiguous Desktop handler contract')
        ui = ui.replace(hook, hook+'''        # META40_DESKTOP_INTEGRATION
        from meta40_desktop import handle as handle_meta40
        if handle_meta40(self, CORE_DIR, CORE_URL, PORT, bool(account_state())):
            return
''')
    main += '\n'+CORE_MARK+'\nfrom meta40.api import install as install_meta40\ninstall_meta40(app)\n'
    pending += '\n'+PENDING_PATCH
    files = {('core','main.py'):main.encode(), ('core','agent_pending.py'):pending.encode(),
             ('desktop','meta_desktop.py'):ui.encode(),
             ('desktop','assets/app.js'):(js+'\n'+text(HERE/'desktop/agent40.js')).encode(),
             ('desktop','meta40_desktop.py'):(HERE/'desktop/meta40_desktop.py').read_bytes()}
    for p in (HERE/'core/meta40').glob('*.py'):
        files['core','meta40/'+p.name] = p.read_bytes()
    config = {'version':'4.0.0', 'projects':str(projects), 'token':secrets.token_urlsafe(48)}
    files['core','meta40_config.json'] = json.dumps(config, indent=2).encode()
    for (_, name), raw in files.items():
        if name.endswith('.py'): ast.parse(raw.decode(), filename=name)
    return files


def checked_target(roots, area, name):
    if area not in roots or not isinstance(name, str) or '\\' in name:
        raise ValueError('Invalid manifest target')
    target = roots[area]/name
    if not target.resolve().is_relative_to(roots[area]) or target.resolve() == roots[area]:
        raise ValueError('Manifest target outside installation')
    for p in [target, *target.parents]:
        if p.exists() and (p.is_symlink() or getattr(p.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Links / junctions not allowed in install paths')
        if p == roots[area]: break
    return target


def rollback(manifest_path, core, desktop):
    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    roots = {'core':core.resolve(), 'desktop':desktop.resolve()}
    if data['roots'] != {k:str(v) for k,v in roots.items()}:
        raise ValueError('Rollback roots differ from manifest; supply matching --core and --desktop')
    prepared = []
    for entry in data['files']:
        target = checked_target(roots, entry['area'], entry['path'])
        current = target.read_bytes() if target.exists() else None
        # Supports repeating rollback after an interrupted rollback operation.
        if sha(current) not in (entry['installed_hash'], entry['before_hash']):
            raise ValueError('Later edits found; rollback refused: '+str(target))
        raw = None
        if entry['before_hash'] is not None:
            backup = manifest_path.parent/entry['backup']
            if not backup.resolve().is_relative_to(manifest_path.parent.resolve()):
                raise ValueError('Invalid backup path')
            raw = backup.read_bytes()
            if sha(raw) != entry['before_hash']: raise ValueError('Corrupt backup: '+str(backup))
        prepared.append((target, raw))
    for target, raw in reversed(prepared):
        if raw is None: target.unlink(missing_ok=True)
        else: write(target, raw)
    data['status'] = 'rolled_back'
    write(manifest_path, json.dumps(data, indent=2).encode())
    print('META 4.0 update rolled back. Restart Core and Desktop.')


def install(core, desktop, projects, check=False):
    roots = {'core':core.resolve(), 'desktop':desktop.resolve()}
    core, desktop = roots['core'], roots['desktop']
    for p in (core/'main.py', core/'agent_pending.py', core/'agent_tools.py', desktop/'meta_desktop.py', desktop/'assets/app.js'):
        if not p.is_file(): raise ValueError('Required file missing: '+str(p))
    # The existing approval layer owns the workspace boundary. Do not silently
    # configure the new API against a different project tree.
    tree = ast.parse(text(core/'agent_tools.py'))
    actual_projects = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'WORKSPACE' for t in node.targets):
            for child in ast.walk(node.value):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == 'Path' and child.args and isinstance(child.args[0], ast.Constant):
                    actual_projects = Path(child.args[0].value).resolve()
    if actual_projects != projects.resolve():
        raise ValueError('--projects must match WORKSPACE in existing agent_tools.py: '+str(actual_projects))
    if not projects.is_dir():
        raise ValueError('Projects directory must exist: '+str(projects))
    files = replacements(core, desktop, projects)
    prepared = []
    for (area, name), raw in files.items():
        target = checked_target(roots, area, name)
        old = target.read_bytes() if target.exists() else None
        prepared.append((area, name, target, old, raw))
    if check:
        print('Compatibility check passed: '+str(len(files))+' files; no changes written.')
        return
    backup = core/'meta40_backups'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup.mkdir(parents=True)
    manifest_path = backup/'manifest.json'
    manifest = {'version':'4.0.0', 'status':'prepared', 'roots':{k:str(v) for k,v in roots.items()}, 'files':[]}
    for i, (area, name, target, old, raw) in enumerate(prepared):
        location = str(i)+'.bak'
        if old is not None: write(backup/location, old)
        manifest['files'].append({'area':area, 'path':name, 'backup':location,
                                 'before_hash':sha(old), 'installed_hash':sha(raw)})
    write(manifest_path, json.dumps(manifest, indent=2).encode())
    written = []
    try:
        for area, name, target, old, raw in prepared:
            current = target.read_bytes() if target.exists() else None
            if sha(current) != sha(old): raise RuntimeError('File changed during installation: '+str(target))
            write(target, raw); written.append((target, old))
        manifest['status'] = 'installed'
        write(manifest_path, json.dumps(manifest, indent=2).encode())
    except BaseException:
        failures = []
        for target, old in reversed(written):
            try:
                if old is None: target.unlink(missing_ok=True)
                else: write(target, old)
            except OSError as exc: failures.append(str(exc))
        manifest['status'] = 'rollback_incomplete' if failures else 'rolled_back'
        manifest['errors'] = failures
        write(manifest_path, json.dumps(manifest, indent=2).encode())
        raise
    print('META 4.0 installed. Restart Core and Desktop.')
    print('Rollback manifest: '+str(manifest_path))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--core', type=Path, default=Path(r'D:\META\Core'))
    p.add_argument('--desktop', type=Path, default=Path.home()/'Downloads/META_1_3_Hotfix')
    p.add_argument('--projects', type=Path, default=Path(r'D:\META\Projects'))
    p.add_argument('--check', action='store_true')
    p.add_argument('--rollback', type=Path)
    a = p.parse_args()
    try:
        if a.rollback: rollback(a.rollback.resolve(), a.core, a.desktop)
        else: install(a.core, a.desktop, a.projects.resolve(), a.check)
    except Exception as exc:
        print('ERROR: '+str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
