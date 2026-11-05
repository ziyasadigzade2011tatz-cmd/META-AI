import json,os,math
from pathlib import Path
from .understanding_config import ROOT

def load(name):
    defaults=json.loads((ROOT/(name+'.json')).read_text('utf-8'))
    local=Path(os.environ.get('META_CORE_CONFIG_DIR',str(ROOT)))/(name+'.json')
    if local.resolve()==(ROOT/(name+'.json')).resolve():return defaults
    try:value=json.loads(local.read_text('utf-8'))
    except (OSError,ValueError):return defaults
    if not isinstance(value,dict):return defaults
    for key,candidate in value.items():
        if key not in defaults:continue
        original=defaults[key]
        if type(original) is bool and type(candidate) is bool:defaults[key]=candidate
        elif type(original) in (int,float) and type(candidate) in (int,float) and math.isfinite(candidate) and candidate>=0:defaults[key]=candidate
        elif isinstance(original,str) and isinstance(candidate,str) and len(candidate)<=200:defaults[key]=candidate
        elif isinstance(original,list) and isinstance(candidate,list) and len(candidate)<=200 and all(isinstance(s,str) and len(s)<=200 for s in candidate):defaults[key]=candidate
    return defaults
