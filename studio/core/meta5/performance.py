"""Latency tuning that preserves model weights, context and generation limits."""
import json,math,os,re
from pathlib import Path

DEFAULT={'enabled':True,'keep_alive_seconds':900,'simple_turn_fast_path':True,
         'greeting_limit_seconds':20,'preferred_chat_model':'qwen3.5:4b','fallback_chat_model':'qwen2.5:3b'}

def settings():
    bundled=Path(__file__).resolve().parents[1]/'config/performance.json'
    local=Path(os.environ.get('META_CORE_CONFIG_DIR',str(bundled.parent)))/'performance.json'
    result=dict(DEFAULT)
    for path in dict.fromkeys((bundled,local)):
        try:value=json.loads(path.read_text('utf-8'))
        except (OSError,ValueError):continue
        if not isinstance(value,dict):continue
        for key,default in DEFAULT.items():
            candidate=value.get(key)
            if type(default) is bool and type(candidate) is bool:result[key]=candidate
            elif type(default) is int and type(candidate) in (int,float) and math.isfinite(candidate):result[key]=candidate
            elif type(default) is str and isinstance(candidate,str) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}',candidate):result[key]=candidate
    result['keep_alive_seconds']=int(max(0,min(3600,result['keep_alive_seconds'])))
    result['greeting_limit_seconds']=max(1,min(120,result['greeting_limit_seconds']))
    return result

def keep_alive():
    cfg=settings()
    return cfg['keep_alive_seconds'] if cfg['enabled'] else '3m'

def simple_turn(text):
    cfg=settings()
    return bool(cfg['enabled'] and cfg['simple_turn_fast_path'] and re.fullmatch(
        r'\s*(?:привет|приветик|здравствуй(?:те)?|доброе утро|добрый (?:день|вечер)|спасибо|благодарю|пока|до свидания|hello|hi|thanks)[\s!.,🙂😊👋]*',text,re.I))

def choose_measured_model(rows):
    """No benchmark evidence means no automatic downgrade."""
    cfg=settings();preferred=cfg['preferred_chat_model']
    samples=[r for r in rows if r.get('model')==preferred and r.get('characters',0)>0 and type(r.get('total_seconds')) in (float,int)]
    if samples and max(r['total_seconds'] for r in samples)>cfg['greeting_limit_seconds']:
        return cfg['fallback_chat_model'],'greeting_exceeded_threshold'
    return preferred,'greeting_within_threshold' if samples else 'not_benchmarked'
