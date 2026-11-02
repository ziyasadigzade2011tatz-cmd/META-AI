"""Public HTTPS research for META 4.6.

Features: DDGS backend failover, short in-memory cache, result normalization,
HTML extraction and pinned-IP HTTPS fetch with redirect + SSRF controls.
No cookies, shell commands, local/private IP access, or arbitrary downloads.
Web results MUST be treated as untrusted data by the agent.
"""
from __future__ import annotations
import ipaddress
import copy
import re
import socket
import threading
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

MAX_BYTES = 650_000
MAX_TEXT = 16_000
USER_AGENT = 'META-Research/4.6 (public-web; read-only)'
SEARCH_TIMEOUT = 6
SEARCH_BUDGET = 20
_CACHE_TTL = 180
_CACHE_LIMIT = 80
_cache = {}
_cache_lock = threading.RLock()


class WebError(ValueError):
    pass


class _Readable(HTMLParser):
    SKIP = {'script', 'style', 'svg', 'noscript', 'iframe', 'form', 'nav', 'footer'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts = []
        self.title = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP: self.skip += 1
        if tag == 'title': self.in_title = True
        if tag in ('p', 'h1', 'h2', 'h3', 'h4', 'li', 'br', 'article', 'section', 'div'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip: self.skip -= 1
        if tag == 'title': self.in_title = False

    def handle_data(self, text):
        if self.in_title: self.title.append(text)
        if not self.skip and not self.in_title: self.parts.append(text)


def _clean(value):
    return re.sub(r'\n{3,}', '\n\n', re.sub(r'[ \t]+', ' ', value)).strip()


def _public_url(raw):
    if not isinstance(raw, str) or not 1 <= len(raw) <= 2048:
        raise WebError('Invalid URL')
    try:
        url = urlsplit(raw.strip())
        host = (url.hostname or '').encode('idna').decode('ascii').lower().rstrip('.')
        port = url.port or 443
    except (ValueError, UnicodeError) as exc:
        raise WebError('Malformed URL') from exc
    if url.scheme.lower() != 'https' or not host or url.username or url.password or port != 443:
        raise WebError('Only public HTTPS websites on port 443 are allowed')
    if (host in {'localhost','localhost.localdomain'} or
            host.endswith(('.localhost','.internal','.local')) or '%' in host or
            any(ch.isspace() for ch in host)):
        raise WebError('Local or invalid hostname blocked')
    try:
        address=ipaddress.ip_address(host)
    except ValueError:
        address=None
    if address is not None and not address.is_global:
        raise WebError('Non-public network destination blocked')
    authority='['+host+']' if ':' in host else host
    normalized = urlunsplit(('https', authority, url.path or '/', url.query, ''))
    return normalized, host


def _resolve(host):
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise WebError('DNS resolution failed') from exc
    ips = list(dict.fromkeys(item[4][0] for item in addresses))
    if not ips:
        raise WebError('No DNS addresses')
    for ip in ips:
        try:
            if not ipaddress.ip_address(ip).is_global:
                raise WebError('Non-public network destination blocked')
        except ValueError as exc:
            if isinstance(exc, WebError): raise
            raise WebError('Invalid DNS address') from exc
    return ips


def _search_once(query, backend, limit, timeout=SEARCH_TIMEOUT):
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise WebError('Missing dependency: install ddgs in META Core .venv') from exc
    return DDGS(timeout=timeout).text(query, backend=backend, max_results=limit) or []


def web_search(query: str, max_results: int=5):
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 300:
        raise WebError('Search query length must be 2..300')
    query = query.strip()
    try: limit = max(1, min(int(max_results), 8))
    except (ValueError, TypeError) as exc: raise WebError('Invalid result limit') from exc
    key = (query.casefold(), limit)
    with _cache_lock:
        record = _cache.get(key)
        if record and time.monotonic() - record[0] < _CACHE_TTL:
            return {**copy.deepcopy(record[1]), 'cached': True}
    # Automatic routing is first: the user's network previously succeeded here
    # even when forcing Bing and Brave produced no results.
    errors = []
    raw_hits = []
    started=time.monotonic()
    for backend in ('auto', 'duckduckgo', 'bing', 'brave'):
        remaining=SEARCH_BUDGET-(time.monotonic()-started)
        if remaining<=0:break
        try:
            rows = _search_once(query, backend, limit,timeout=min(SEARCH_TIMEOUT,remaining))
            # A provider returning only malformed/private/non-HTTPS hits has
            # not succeeded. Continue failover instead of failing after break.
            for row in rows:
                if not isinstance(row,dict):continue
                try: _public_url(row.get('href') or row.get('url') or '')
                except WebError:continue
                raw_hits.append(row)
            if raw_hits: break
            errors.append(backend + ': no usable HTTPS results')
        except WebError:
            raise
        except Exception as exc:
            errors.append(backend + ': ' + type(exc).__name__+': '+str(exc).replace('\n',' ')[:150])
    if not raw_hits:
        raise WebError('Search providers unavailable (' + '; '.join(errors[:4]) + ')')
    seen = set()
    results = []
    for row in raw_hits:
        if not isinstance(row, dict): continue
        try: normalized, host = _public_url(row.get('href') or row.get('url') or '')
        except WebError: continue
        if normalized in seen: continue
        seen.add(normalized)
        results.append({
            'title': str(row.get('title', ''))[:180],
            'url': normalized,
            'snippet': str(row.get('body', row.get('snippet', '')))[:900],
            'domain': host,
        })
        if len(results) >= limit: break
    if not results:
        raise WebError('Search returned no usable public HTTPS links')
    payload = {'query': query, 'results': results, 'count': len(results),
               'source': 'public_search_untrusted', 'cached': False}
    with _cache_lock:
        if len(_cache) >= _CACHE_LIMIT:
            oldest = min(_cache, key=lambda item: _cache[item][0])
            _cache.pop(oldest, None)
        _cache[key] = (time.monotonic(), copy.deepcopy(payload))
    return payload


def web_fetch(url: str, *, max_redirects=3):
    """Read public HTML/plaintext only; pin verified DNS IP to TLS SNI hostname.

    The caller must separately ensure the initial URL came from a search result.
    """
    try: import urllib3
    except ImportError as exc: raise WebError('Missing dependency: install urllib3') from exc
    current = url
    for _ in range(max(0, min(int(max_redirects), 5)) + 1):
        normalized, host = _public_url(current)
        ip = _resolve(host)[0]
        # Pin the validated IP. Keep SNI & TLS certificate checks for the DNS hostname.
        pool = urllib3.HTTPSConnectionPool(
            ip, port=443, server_hostname=host, assert_hostname=host,
            timeout=urllib3.Timeout(connect=4, read=9), retries=False, maxsize=1,
        )
        try:
            p = urlsplit(normalized)
            path = (p.path or '/') + (('?' + p.query) if p.query else '')
            response = pool.request('GET', path, headers={
                'Host': host, 'User-Agent': USER_AGENT,
                'Accept': 'text/html,text/plain;q=0.9,*/*;q=0.1',
                'Accept-Encoding': 'identity',
            }, preload_content=False, redirect=False)
            try:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get('Location')
                    if not location: raise WebError('Redirect missing Location')
                    current = urljoin(normalized, location)
                    continue
                if response.status != 200:
                    raise WebError('HTTP ' + str(response.status))
                ctype = response.headers.get('Content-Type', '').lower()
                if not (ctype.startswith('text/html') or ctype.startswith('text/plain')):
                    raise WebError('Unsupported content type')
                payload = response.read(MAX_BYTES + 1)
                if len(payload) > MAX_BYTES:
                    raise WebError('Page exceeded size limit')
                m = re.search(r'charset=["\']?([a-zA-Z0-9._-]+)', ctype)
                charset = m.group(1) if m else 'utf-8'
                try: decoded = payload.decode(charset, errors='replace')
                except LookupError: decoded = payload.decode('utf-8', errors='replace')
                if ctype.startswith('text/html'):
                    # MediaWiki puts large cross-game menus before the article.
                    # Keep the article at the front of the bounded evidence.
                    article=re.search(r'<(?:div|main)\b[^>]*\bid=["\']mw-content-text["\'][^>]*>',decoded,re.I)
                    if article:decoded=decoded[article.end():]
                    parser = _Readable()
                    parser.feed(decoded)
                    title = _clean(' '.join(parser.title))[:200]
                    text = _clean(''.join(parser.parts))
                else:
                    title, text = '', _clean(decoded)
                return {'url': normalized, 'title': title, 'text': text[:MAX_TEXT],
                        'truncated': len(text) > MAX_TEXT,
                        'source': 'public_web_untrusted'}
            finally:
                response.close()
                response.release_conn()
        except (urllib3.exceptions.HTTPError, OSError, TimeoutError) as exc:
            raise WebError('Page retrieval failed: ' + type(exc).__name__) from exc
        finally:
            pool.close()
    raise WebError('Too many redirects')
