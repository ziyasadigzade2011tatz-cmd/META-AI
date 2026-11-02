"""Same-origin authenticated Desktop proxy. Core token never reaches JavaScript."""
import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler


def handle(handler, core_dir, core_url, port, configured):
    path = urlsplit(handler.path).path
    if not path.startswith('/api/meta40/'):
        return False
    try:
        if handler.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            handler.json_response({'error':'Invalid host'}, 403)
            return True
        if not configured or not handler.authorized():
            handler.json_response({'error':'Создай локальный профиль и войди в него.'}, 403)
            return True
        suffix = path[len('/api/meta40'):]
        allowed = (handler.command == 'GET' and re.fullmatch(r'/(?:status|models|tasks(?:/[a-f0-9]{32})?)', suffix))
        allowed = allowed or (handler.command == 'POST' and re.fullmatch(r'/tasks(?:/[a-f0-9]{32}/cancel)?', suffix))
        if not allowed:
            handler.json_response({'error':'Route not allowed'}, 404)
            return True
        body = None
        if handler.command == 'POST':
            if handler.headers.get('Origin') not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
                handler.json_response({'error':'Same-origin request required'}, 403)
                return True
            length = int(handler.headers.get('Content-Length', '0'))
            if not 0 <= length <= 64000:
                raise ValueError('Request too large')
            body = handler.rfile.read(length) or b'{}'
        config = json.loads((Path(core_dir)/'meta40_config.json').read_text(encoding='utf-8'))
        request = Request(core_url+'/agent40'+suffix, body,
                          {'Content-Type':'application/json', 'X-Meta40-Token':config['token']}, method=handler.command)
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(request, timeout=10) as r:
                handler.json_response(json.loads(r.read(8_000_000)), r.status)
        except HTTPError as exc:
            data = json.loads(exc.read(64000))
            handler.json_response({'error':data.get('detail', data)}, exc.code)
    except Exception as exc:
        handler.json_response({'error':str(exc)}, 503)
    return True
