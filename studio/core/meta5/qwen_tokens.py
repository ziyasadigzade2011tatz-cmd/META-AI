"""Local Qwen35 text token counting from GGUF vocabulary; no tensor loading.

Pre-tokenization mirrors llama.cpp LLAMA_VOCAB_PRE_TYPE_QWEN35. Chat framing
mirrors Ollama 0.40.15 model/renderers/qwen35.go for text messages without tools.
Unsupported tokenizers/renderers fail explicitly rather than claiming precision.
"""
import functools
import json
from pathlib import Path
import re
import struct
import unicodedata
import threading
from collections import OrderedDict

WHITE_SPACE='\t\n\v\f\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000'


def _read(handle, fmt):
    size=struct.calcsize(fmt);data=handle.read(size)
    if len(data)!=size:raise ValueError('Incomplete GGUF metadata')
    return struct.unpack(fmt,data)[0]


def _string(handle, keep=True):
    size=_read(handle,'<Q')
    if size>32*1024*1024:raise ValueError('GGUF metadata string too large')
    if not keep:handle.seek(size,1);return None
    value=handle.read(size)
    if len(value)!=size:raise ValueError('Incomplete GGUF string')
    return value.decode('utf-8')


def vocabulary(path):
    wanted={'tokenizer.ggml.tokens','tokenizer.ggml.merges','tokenizer.ggml.token_type',
            'tokenizer.ggml.pre','tokenizer.ggml.model','tokenizer.ggml.add_bos_token'}
    scalars={0:'<B',1:'<b',2:'<H',3:'<h',4:'<I',5:'<i',6:'<f',7:'<?',10:'<Q',11:'<q',12:'<d'}
    def value(handle,kind,keep):
        if kind==8:return _string(handle,keep)
        if kind==9:
            child=_read(handle,'<I');count=_read(handle,'<Q')
            if count>2000000 or child==9:raise ValueError('Invalid GGUF metadata array')
            if not keep and child in scalars:handle.seek(struct.calcsize(scalars[child])*count,1);return None
            rows=[]
            for _ in range(count):
                item=value(handle,child,keep)
                if keep:rows.append(item)
            return rows if keep else None
        if kind not in scalars:raise ValueError('Unsupported GGUF metadata type')
        result=_read(handle,scalars[kind]);return result if keep else None
    result={}
    with Path(path).open('rb') as handle:
        if handle.read(4)!=b'GGUF' or _read(handle,'<I') not in (2,3):raise ValueError('Unsupported GGUF')
        _read(handle,'<Q');count=_read(handle,'<Q')
        if count>100000:raise ValueError('Invalid GGUF metadata count')
        for _ in range(count):
            key=_string(handle);kind=_read(handle,'<I');item=value(handle,kind,key in wanted)
            if key in wanted:result[key]=item
    return result


def pieces(text):
    """Equivalent Unicode categories for Qwen35's published regex, using stdlib."""
    def cat(c):return unicodedata.category(c)[0]
    i=0;n=len(text)
    while i<n:
        start=i
        if text[i]=="'":
            found=next((s for s in ("'re","'ve","'ll","'s","'t","'m","'d") if text[i:i+len(s)].lower()==s),None)
            if found:i+=len(found);yield text[start:i];continue
        pos=i
        if text[pos] not in '\r\n' and cat(text[pos]) not in ('L','N') and pos+1<n and cat(text[pos+1]) in ('L','M'):pos+=1
        if cat(text[pos]) in ('L','M'):
            i=pos+1
            while i<n and cat(text[i]) in ('L','M'):i+=1
            yield text[start:i];continue
        if cat(text[i])=='N':i+=1;yield text[start:i];continue
        pos=i+1 if text[i]==' ' and i+1<n else i
        if text[pos] not in WHITE_SPACE and cat(text[pos]) not in ('L','M','N'):
            i=pos+1
            while i<n and text[i] not in WHITE_SPACE and cat(text[i]) not in ('L','M','N'):i+=1
            while i<n and text[i] in '\r\n':i+=1
            yield text[start:i];continue
        if text[i] in WHITE_SPACE:
            end=i+1
            while end<n and text[end] in WHITE_SPACE:end+=1
            newline=max(text.rfind('\n',i,end),text.rfind('\r',i,end))
            i=newline+1 if newline>=i else end if end==n or end-i==1 else end-1
            yield text[start:i];continue
        raise ValueError('Unsupported tokenizer character')


class Qwen35:
    def __init__(self,path):
        self._segments=OrderedDict();self._segments_size=0;self._segments_lock=threading.Lock()
        data=vocabulary(path)
        if data.get('tokenizer.ggml.pre')!='qwen35' or data.get('tokenizer.ggml.model')!='gpt2' or data.get('tokenizer.ggml.add_bos_token',False):raise ValueError('Only Qwen35 byte BPE supported')
        tokens=data['tokenizer.ggml.tokens'];types=data['tokenizer.ggml.token_type']
        if len(tokens)!=len(types):raise ValueError('Invalid GGUF vocabulary')
        self.ranks={tuple(pair.split(' ',1)):i for i,pair in enumerate(data['tokenizer.ggml.merges'])}
        self.vocab=set(tokens)
        special=[t for t,k in zip(tokens,types) if k in (3,4) and t]
        self.special=re.compile('('+ '|'.join(re.escape(t) for t in sorted(special,key=len,reverse=True))+')') if special else None
        byte_values=list(range(33,127))+list(range(161,173))+list(range(174,256))
        chars=byte_values[:];extra=0
        for b in range(256):
            if b not in byte_values:byte_values.append(b);chars.append(256+extra);extra+=1
        self.bytes=dict(zip(byte_values,map(chr,chars)))

    @functools.lru_cache(maxsize=12000)
    def word(self,text):
        if len(text.encode('utf-8'))>8192:raise ValueError('Tokenizer word limit')
        word=tuple(self.bytes[b] for b in text.encode('utf-8'))
        while len(word)>1:
            ranked=[(self.ranks.get(pair,float('inf')),pair) for pair in zip(word,word[1:])]
            rank,pair=min(ranked,key=lambda x:x[0])
            if rank==float('inf'):break
            merged=[];i=0
            while i<len(word):
                if i+1<len(word) and (word[i],word[i+1])==pair:merged.append(word[i]+word[i+1]);i+=2
                else:merged.append(word[i]);i+=1
            word=tuple(merged)
        if any(t not in self.vocab for t in word):raise ValueError('Unrepresentable token')
        return len(word)

    def count(self,text):
        if not isinstance(text,str) or len(text)>2000000:raise ValueError('Text tokenization limit')
        parts=self.special.split(text) if self.special else [text]
        return sum(1 if self.special and self.special.fullmatch(part) else self.count_segment(part) for part in parts if part)

    def count_segment(self,text):
        # Cache unchanged message segments, not whole growing conversations.
        # Bounded to 64 segments / 256k characters per tokenizer.
        if len(text)>20000:return sum(self.word(p) for p in pieces(text))
        with self._segments_lock:
            if text in self._segments:
                self._segments.move_to_end(text);return self._segments[text]
        result=sum(self.word(p) for p in pieces(text))
        with self._segments_lock:
            if text not in self._segments:self._segments_size+=len(text)
            self._segments[text]=result
            while len(self._segments)>64 or self._segments_size>256000:
                old,_=self._segments.popitem(last=False);self._segments_size-=len(old)
        return result


def render(messages,think=False):
    """Qwen35 text framing; reject images/tool calls rather than undercount."""
    parts=[]
    for i,message in enumerate(messages):
        role=message.get('role');content=message.get('content','')
        if role not in ('system','user','assistant') or not isinstance(content,str) or message.get('images') or message.get('tool_calls'):raise ValueError('Text messages only')
        content=content.strip(WHITE_SPACE)
        if role=='assistant' and '</think>' in content:content=content.split('</think>',1)[1].lstrip('\n')
        parts.append('<|im_start|>'+role+'\n'+content+('<|im_end|>\n' if role!='assistant' or i!=len(messages)-1 else ''))
    # Ollama's qwen3.5 factory sets emitEmptyThinkOnNoThink=true. The empty
    # block is part of the *input*, even when no reasoning is generated.
    if messages and messages[-1].get('role')!='assistant':parts.append('<|im_start|>assistant\n'+('<think>\n' if think else '<think>\n\n</think>\n\n'))
    return ''.join(parts)


@functools.lru_cache(maxsize=2)
def for_model(model):
    import httpx
    from .transport import BASE
    with httpx.Client(timeout=15,trust_env=False) as client:
        version=client.get(BASE+'/api/version');version.raise_for_status()
        if version.json().get('version')!='0.40.15':raise ValueError('Ollama chat framing version not validated')
        response=client.post(BASE+'/api/show',json={'model':model});response.raise_for_status();data=response.json()
    if data.get('renderer')!='qwen3.5' or data.get('messages'):raise ValueError('Unsupported chat renderer or model messages')
    line=next((line[5:].strip().strip('"') for line in data.get('modelfile','').splitlines() if line.startswith('FROM ')),None)
    if not line or not Path(line).is_file():raise ValueError('Local model vocabulary unavailable')
    return Qwen35(line)


def counter(model,think=False):
    tokenizer=for_model(model)
    return lambda messages:tokenizer.count(render(messages,think))


@functools.lru_cache(maxsize=4)
def agent_counter(model):
    """Estimate custom Qwen35 renderers using validated vocabulary + reserve.

    This is deliberately not advertised as exact chat framing. Include model
    preset messages and reserve 1024 tokens for the custom renderer.
    """
    try:
        return counter(model, False)
    except ValueError:
        pass
    import httpx
    from .transport import BASE
    with httpx.Client(timeout=15,trust_env=False) as client:
        response=client.post(BASE+'/api/show',json={'model':model})
        response.raise_for_status();data=response.json()
    if data.get('model_info',{}).get('general.architecture')!='qwen35':
        raise ValueError('Unsupported custom model vocabulary')
    line=next((line[5:].strip().strip('"') for line in data.get('modelfile','').splitlines() if line.startswith('FROM ')),None)
    if not line or not Path(line).is_file():raise ValueError('Local model vocabulary unavailable')
    tokenizer=Qwen35(line)
    preset=data.get('messages') or []
    if not isinstance(preset,list):raise ValueError('Unsupported preset messages')
    overhead=1024+sum(tokenizer.count(str(m.get('content',''))) for m in preset if isinstance(m,dict))
    return lambda messages:tokenizer.count(render(messages,False))+overhead
