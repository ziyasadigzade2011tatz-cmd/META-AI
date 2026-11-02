"""Read-only, allowlisted source inspection for controlled META self-development.

No arbitrary filesystem access; never writes the live installed Core.
Generated changes must be staged in a normal Project and manually reviewed.
"""
from __future__ import annotations
from pathlib import Path

ALLOWED = {
    'meta5/context.py','meta5/dialogue.py','meta5/transport.py','meta5/models.py',
    'meta5/tools.py','meta5/project.py','meta5/agent.py','meta5/jobs.py','meta5/api.py',
    'meta5/changes.py','meta5/memory.py','meta5/research.py','meta5/git_tools.py',
    'meta5/process.py','meta5/benchmarks.py',
    'meta40/__init__.py', 'meta40/api.py', 'meta40/context.py', 'meta40/engine.py',
    'meta40/memory.py', 'meta40/proposals.py', 'meta40/runner.py',
    'meta40/selfdev.py', 'meta40/web_research.py', 'meta40/web_tools.py',
    'meta40/workspace.py',
    'main.py', 'agent_chat.py', 'meta_web_bridge.py',
}
MAX_SOURCE_BYTES = 24_000


def self_inspect(path=None):
    """Only predefined source files from the installed Core, never secrets/config."""
    if path is None:
        return {'files': sorted(ALLOWED), 'access': 'read_only',
                'warning': 'Source in installed Core cannot be modified through this tool.'}
    if not isinstance(path, str) or path not in ALLOWED:
        raise ValueError('Self-inspection path not allowlisted')
    core = Path(__file__).resolve().parent.parent
    target = core.joinpath(*path.split('/'))
    if target.is_symlink() or not target.is_file():
        raise ValueError('Source file not found or is a link')
    # Includes check on reparse points in parent chain, including Windows junctions.
    for piece in (target, *target.parents):
        if piece.exists() and (piece.is_symlink() or (getattr(piece.stat(), 'st_file_attributes', 0) & 0x400)):
            raise ValueError('Linked source path not allowed')
        if piece == core: break
    if not target.resolve().is_relative_to(core.resolve()):
        raise ValueError('Source escapes META Core')
    if target.stat().st_size > MAX_SOURCE_BYTES:
        return {'path': path, 'error': 'Source exceeds inspection size; inspect smaller modules first'}
    return {'path': path, 'content': target.read_text(encoding='utf-8'),
            'read_only': True, 'live_core_modified': False}


def self_assess(snapshot, edits):
    paths = sorted(set(snapshot) | set(edits))
    return {
        'status': 'inspection_ready',
        'project_files': len(paths),
        'candidate_project_files': [p for p in paths if p.endswith('.py')][:40],
        'installed_source_inspection': 'Use self_inspect with a source path from its allowlist',
        'safe_patch_workflow': ('Create replacement source in the selected META Projects folder; '
                                'review the pending diff; run tests if authorized; '
                                'install approved files manually after a backup/restart.'),
        'auto_install': False,
    }
