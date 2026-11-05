"""Bundled defaults with local overrides; never includes credentials."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'config'

def settings():
    value = json.loads((ROOT / 'understanding.json').read_text('utf-8'))
    override = Path(os.environ.get('META_CORE_CONFIG_DIR', str(ROOT))) / 'understanding.json'
    if override.resolve() != (ROOT / 'understanding.json').resolve() and override.exists():
        extra = json.loads(override.read_text('utf-8'))
        if isinstance(extra, dict): value.update({k:v for k,v in extra.items() if k in value})
    return value

def system_prompt():
    return (ROOT / 'system.md').read_text('utf-8')
