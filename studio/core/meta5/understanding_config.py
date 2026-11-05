"""Bundled defaults with local overrides; never includes credentials."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'config'
OFFLINE_MARKER='META_INTERNAL_WEB_DISABLED_V1'

def settings():
    value = json.loads((ROOT / 'understanding.json').read_text('utf-8'))
    override = Path(os.environ.get('META_CORE_CONFIG_DIR', str(ROOT))) / 'understanding.json'
    if override.resolve() != (ROOT / 'understanding.json').resolve() and override.exists():
        try:extra = json.loads(override.read_text('utf-8'))
        except (OSError,ValueError):return value
        if isinstance(extra, dict):
            for key,candidate in extra.items():
                if key not in value:continue
                default=value[key]
                if isinstance(default,bool) and type(candidate) is bool:value[key]=candidate
                elif type(default) in (int,float) and type(candidate) in (int,float):
                    import math
                    if math.isfinite(candidate) and candidate>=0 and (candidate<=1 if 'threshold' in key else candidate<=10000):value[key]=candidate
    return value

def system_prompt():
    return (ROOT / 'system.md').read_text('utf-8')
