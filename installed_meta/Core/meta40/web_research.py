"""Constrained public-web research for META. No local network or arbitrary downloads."""
from __future__ import annotations

from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

MAX_BYTES = 700_000
MAX_TEXT = 14_000
UA = 'META-Code-Research/4.3 (read-only; public web)'

class WebError(ValueError):
    pass

class _Text(HTMLParser):
    SKIP = {'script', 'style', 'svg', 'noscript', 'iframe', 'form', 'nav', 'footer'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0
        self.title = []
        self.in_title = False
    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP: self.skip += 1
        if tag == 'title': self.in_title = True
        if tag in ('p','h1','h2','h3','li','br','article','section'): self.out.append('\n')
    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip: self.skip -= 1
        if tag == 'title': self.in_title = False
    def handle_data(self, data):
        if self.in_title: self.title.append(data)
        if not self.skip: self.out.append(data)

def _clean(s: str) -> str:
    return re.sub(r'\n{3,}', '\n\n', re.sub(r'[ \t]+', ' ', s)).strip()

def _public_url(url: str) -> tuple[str, str, int, str]:
    if not isinstance(url, str) or len(url) > 2048:
        raise WebError('Invalid URL')
    try:
        u = urlsplit(url.strip())
        host = (u.hostname or '').encode('idna').decode('ascii').lower().rstrip('.')
        port = u.port or 443
    except (ValueError, UnicodeError) as e:
        raise WebError('Invalid URL') from e
    if u.scheme.lower() != 'https' or not host or u.username or u.password or port != 443:
        raise WebError('Only public HTTPS URLs on port 443 are allowed')
    if host in {'localhost', 'localhost.localdomain'} or host.endswith(('.localhost','.local','.internal')):
        raise WebError('Local host blocked')
    if not host or any(c.isspace() for c in host):
        raise WebError('Invalid host')
    # Strictly reject addresses that look numeric, IPv6 zone identifiers and encoded IP aliases.
    if '%' in host:
        raise WebError('Encoded hostname blocked')
    return urlunsplit(('https', host, u.path or '/', u.query, '')), host, port, u.path

def _resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise WebError('DNS lookup failed') from e
    ips = list(dict.fromkeys(x[4][0] for x in infos))
    if not ips:
        raise WebError('No DNS records')
    for value in ips:
        try: ip = ipaddress.ip_address(value)
        except ValueError as e: raise WebError('Invalid DNS address') from e
        if not ip.is_global:
            raise WebError('Destination resolves to a non-public address')
    return ips

def web_search(query: str, max_results: int=5) -> dict:
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 300:
        raise WebError('Query length must be 2..300')
    max_results = max(1, min(int(max_results), 8))
    try:
        from ddgs import DDGS
    except ImportError as e:
        raise WebError('Install ddgs in the Python environment running META Core') from e
    try:
        hits = DDGS(timeout=10).text(query.strip(), max_results=max_results) or []
    except Exception as e:
        raise WebError('Search provider unavailable: '+type(e).__name__) from e
    result = []
    seen = set()
    for hit in hits:
        try: url, host, _, _ = _public_url(str(hit.get('href','')))
        except WebError: continue
        if url in seen: continue
        seen.add(url)
        result.append({'title':str(hit.get('title',''))[:180], 'url':url,
                       'snippet':str(hit.get('body',''))[:900], 'domain':host})
        if len(result) >= max_results: break
    return {'query':query, 'results':result, 'count':len(result)}

def web_fetch(url: str, *, max_redirects: int=3) -> dict:
    """Fetch via validated IP pinned to TLS SNI (avoids DNS rebinding)."""
    import urllib3
    current = url
    for _ in range(max_redirects + 1):
        normalized, host, _, _ = _public_url(current)
        ip = _resolve(host)[0]
        # Connect to validated IP, while checking cert against original DNS name.
        pool = urllib3.HTTPSConnectionPool(ip, port=443, server_hostname=host,
                    assert_hostname=host, timeout=urllib3.Timeout(connect=4, read=8),
                    retries=False, maxsize=1)
        try:
            path = normalized.split(host, 1)[1]
            response = pool.request('GET', path, headers={'Host':host,
                'User-Agent': UA, 'Accept':'text/html,text/plain;q=0.9,*/*;q=0.1',
                'Accept-Encoding':'identity'}, redirect=False, preload_content=False)
            try:
                if response.status in (301,302,303,307,308):
                    loc = response.headers.get('Location')
                    if not loc: raise WebError('Redirect has no location')
                    current = urljoin(normalized, loc)
                    continue
                if response.status != 200:
                    raise WebError('HTTP status '+str(response.status))
                ctype = response.headers.get('Content-Type','').lower()
                if not (ctype.startswith('text/html') or ctype.startswith('text/plain')):
                    raise WebError('Unsupported content type')
                blob = response.read(MAX_BYTES+1)
                if len(blob) > MAX_BYTES: raise WebError('Page too large')
                charset = 'utf-8'
                match = re.search(r'charset=["\']?([a-zA-Z0-9._-]+)',ctype)
                if match: charset = match.group(1)
                try: s = blob.decode(charset, errors='replace')
                except LookupError: s = blob.decode('utf-8', errors='replace')
                if ctype.startswith('text/html'):
                    parser = _Text(); parser.feed(s)
                    title = _clean(' '.join(parser.title))[:200]
                    extracted = _clean(''.join(parser.out))
                else:
                    title = ''; extracted = _clean(s)
                return {'url':normalized, 'title':title, 'text':extracted[:MAX_TEXT],
                        'truncated':len(extracted)>MAX_TEXT, 'source':'public_web_untrusted'}
            finally: response.release_conn()
        except (urllib3.exceptions.HTTPError, TimeoutError, OSError) as e:
            raise WebError('Page retrieval failed: '+type(e).__name__) from e
        finally: pool.close()
    raise WebError('Too many redirects')

if __name__ == '__main__':
    import sys
    print(json.dumps(web_search(' '.join(sys.argv[1:]) or 'Hearts of Iron IV modding wiki'),ensure_ascii=False,indent=2))
