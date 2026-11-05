"""Incremental source-link checks, preserving code examples and text streaming."""
import re
from urllib.parse import urlsplit,urlunsplit


def canonical(url):
    try:p=urlsplit(url)
    except ValueError:return ''
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path or '/',p.query,''))


class LinkFilter:
    def __init__(self,sources,strict=False):
        self.strict=strict
        self.allowed={canonical(s[k]) for s in sources for k in ('url','resolved_url') if s.get(k) and (not strict or s.get('opened'))}
        self.buffer='';self.fences=0;self.removed=0
    def feed(self,text,final=False):
        self.buffer+=text;out=[]
        def emit(value):
            self.fences+=value.count('```');out.append(value)
        while self.buffer:
            start=re.search(r'https?://',self.buffer,re.I)
            if not start:
                n=len(self.buffer) if final else max(0,len(self.buffer)-10)
                if not n:break
                # Avoid splitting a fenced-code delimiter across chunks.
                while n and n<len(self.buffer) and self.buffer[n-1]=='`':n-=1
                if not n:break
                emit(self.buffer[:n]);self.buffer=self.buffer[n:];continue
            if start.start():emit(self.buffer[:start.start()]);self.buffer=self.buffer[start.start():]
            match=re.match(r'https?://[^\s<>\)\]"\']+',self.buffer,re.I)
            if not match:break
            if match.end()==len(self.buffer) and not final and len(self.buffer)<2200:break
            raw=match.group();url=raw.rstrip('.,;!?');tail=raw[len(url):]
            if (self.fences%2 and not self.strict) or canonical(url) in self.allowed:emit(url+tail)
            else:self.removed+=1;emit('[неподтверждённая ссылка]'+tail)
            self.buffer=self.buffer[match.end():]
        if final and self.buffer:emit(self.buffer);self.buffer=''
        return ''.join(out)
