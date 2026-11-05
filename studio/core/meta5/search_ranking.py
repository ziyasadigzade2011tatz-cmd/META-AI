"""RRF, domain policy and bounded source/chunk ranking, with lexical fallback."""
import json,re,math,os,time
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
from .understanding_config import ROOT
from .storage import STATE
from .phase11_config import load
from .relevance import terms

def domains():
    default=json.loads((ROOT/'search_domains.json').read_text('utf-8'))
    local=Path(os.environ.get('META_CORE_CONFIG_DIR',str(STATE/'config')))/'search_domains.json'
    try:value=json.loads(local.read_text('utf-8'))
    except (OSError,ValueError):return default
    for key in ('blocked','allowed'):
        if isinstance(value.get(key),list) and all(valid_domain(d) for d in value[key]):default[key]=value[key][:500]
    if isinstance(value.get('trusted'),dict):
        for key,items in value['trusted'].items():
            if isinstance(items,list) and all(valid_domain(d) for d in items):default['trusted'][key]=items[:100]
    return default

def valid_domain(value):return isinstance(value,str) and bool(re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,250}\.[a-z]{2,30}',value)) and '..' not in value
def host(url):
    try:return (urlsplit(url).hostname or '').casefold().removeprefix('www.')
    except ValueError:return ''
def matches(domain,pattern):return domain==pattern or domain.endswith('.'+pattern)
def canonical(url):
    try:
        p=urlsplit(url)
        if p.scheme not in ('http','https') or p.username or p.password:return ''
        query=urlencode([(k,v) for k,v in parse_qsl(p.query) if not k.casefold().startswith('utm_') and k not in ('fbclid','gclid')])
        return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/') or '/',query,''))
    except ValueError:return ''
def allowed(url,query,policy=None):
    policy=policy or domains();domain=host(url)
    if not canonical(url) or not domain:return False
    if not load('search')['domain_filter']:return True
    if any(matches(domain,d) for d in policy['allowed']):return True
    if not any(matches(domain,d) for d in policy['blocked']):return True
    # An explicit request naming this service/domain can opt into that source.
    aliases={'t.me':('telegram','телеграм'),'telegram.me':('telegram','телеграм'),'vk.com':('вконтакте','vk'),'ok.ru':('одноклассники',)}
    return domain in query.casefold() or any(re.search(r'\b'+re.escape(a)+r'\b',query,re.I) for a in aliases.get(domain,(domain.split('.')[0],)))

def command(text):
    parts=text.strip().split();policy=domains()
    if len(parts)==1:return json.dumps(policy,ensure_ascii=False,indent=2)
    if len(parts)!=3 or parts[1] not in ('block','allow') or not valid_domain(parts[2].casefold()):return '/domains block example.org; /domains allow example.org'
    domain=parts[2].casefold();target='blocked' if parts[1]=='block' else 'allowed';other='allowed' if target=='blocked' else 'blocked'
    policy[target]=sorted(set([*policy[target],domain]));policy[other]=[d for d in policy[other] if d!=domain]
    from .storage import atomic_json,STATE
    # Persist outside bundled source; the same override directory is used at startup.
    folder=Path(os.environ.get('META_CORE_CONFIG_DIR',str(STATE/'config')));folder.mkdir(parents=True,exist_ok=True)
    atomic_json(folder/'search_domains.json',policy);return 'Правило домена сохранено: '+domain

def similarity(query,text):
    a,b=terms(query),terms(text)
    return len(a&b)/max(1,len(a))

def rank(result_sets,query,engine=None,recent=False):
    cfg=load('search');policy=domains();merged={};excluded=[]
    for results in result_sets[:max(1,min(3,int(cfg['max_queries'])))]:
        seen=set()
        for rank,hit in enumerate(results[:20],1):
            url=canonical(hit.get('url',''))
            if not allowed(url,query,policy):excluded.append({'url':url,'reason':'domain_policy'});continue
            if url in seen:continue
            seen.add(url)
            if url not in merged:merged[url]={**hit,'url':url,'rrf':0.}
            merged[url]['rrf']+=1/(60+rank)
    rows=list(merged.values());vectors=None
    if rows and engine:
        vectors=engine.vectors([query,*[(r.get('title','')+' '+r.get('snippet',''))[:1500] for r in rows]])
    from .embeddings import cosine
    for i,row in enumerate(rows):
        domain=host(row['url']);lex=similarity(query,row.get('title','')+' '+row.get('snippet',''))
        sem=max(0.,cosine(vectors[0],vectors[i+1])) if vectors else lex
        trust=any(matches(domain,d) for values in policy['trusted'].values() for d in values)
        stamp=row.get('published_at') or row.get('date') or ''
        fresh=bool(recent and str(__import__('datetime').datetime.now().year) in str(stamp))
        row['relevance_score']=round(cfg['semantic_weight']*sem+cfg['lexical_weight']*lex+cfg['reputation_weight']*trust+cfg['freshness_weight']*fresh+row['rrf'],5)
        row.update(preferred_source=trust,opened=False)
        if lex==0 and (not vectors or sem<.65):row['irrelevant']=True
    counts={};output=[]
    for row in sorted(rows,key=lambda r:-r['relevance_score']):
        domain=host(row['url'])
        if row.get('irrelevant'):excluded.append({'url':row['url'],'reason':'no_topic_match'});continue
        if counts.get(domain,0)>=max(1,min(2,int(cfg['max_per_domain']))):excluded.append({'url':row['url'],'reason':'domain_diversity'});continue
        counts[domain]=counts.get(domain,0)+1;output.append(row)
        if len(output)>=max(1,min(10,int(cfg['max_sources']))):break
    return output,excluded

def chunks(text,query,engine=None):
    cfg=load('search');size=max(200,min(2000,int(cfg['chunk_characters'])))
    lines=[line.strip() for line in text.splitlines() if len(line.strip())>35 and not re.search(r'cookie|войти|подписаться|все права|меню сайта',line,re.I)]
    clean='\n'.join(lines) if lines else text
    clean=clean[:max(1000,min(20000,int(cfg['page_characters'])))];pieces=[]
    for start in range(0,len(clean),max(100,size-150)):
        part=clean[start:start+size]
        if len(part)>40:pieces.append(part)
    vectors=engine.vectors([query,*pieces]) if engine and pieces else None
    from .embeddings import cosine
    ranked=sorted(enumerate(pieces),key=lambda item:-(max(0,cosine(vectors[0],vectors[item[0]+1])) if vectors else similarity(query,item[1])))
    return [{'text':part,'offset':i*max(100,size-150),'score':round(max(0,cosine(vectors[0],vectors[i+1])) if vectors else similarity(query,part),4)} for i,part in ranked[:max(1,min(5,int(cfg['chunks_per_page'])))]]
