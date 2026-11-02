"""Authenticated same-origin proxy and true streaming for the local Desktop."""
import base64
import json
import re
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit,urlencode,parse_qsl
from urllib.request import Request,build_opener,ProxyHandler


def handle(handler,core_dir,core_url,port,configured):
    parsed=urlsplit(handler.path);path=parsed.path
    if not (path.startswith('/api/meta40/') or path in ('/api/message/stream','/api/message/cancel')):return False
    try:
        if handler.headers.get('Host') not in (f'127.0.0.1:{port}',f'localhost:{port}'):
            handler.json_response({'error':'Invalid host'},403);return True
        if not configured or not handler.authorized():handler.json_response({'error':'Войди в локальный профиль META.'},403);return True
        if handler.command=='POST' and handler.headers.get('Origin') not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):
            handler.json_response({'error':'Same-origin request required'},403);return True
        config=json.loads((Path(core_dir)/'meta40_config.json').read_text(encoding='utf-8'))
        opener=build_opener(ProxyHandler({}));headers={'Content-Type':'application/json','X-Meta40-Token':config['token']}
        if path=='/api/message/stream':
            stream_message(handler,core_url,opener,headers);return True
        if path=='/api/message/cancel':
            data=handler.body();cid=str(data.get('conversation_id',''))
            if not re.fullmatch('[a-f0-9]{32}',cid):raise ValueError('Неверный ID чата')
            req=Request(core_url+'/agent40/dialogue/'+cid+'/cancel',b'{}',headers,method='POST')
            with opener.open(req,timeout=5) as r:handler.json_response(json.loads(r.read()))
            return True
        suffix=path[len('/api/meta40'):]
        gets=r'/(?:status|models|model-profiles|model-benchmark|memory|project/(?:index|read|search)|tasks(?:/[a-f0-9]{32}(?:/artifacts/screenshot\.png)?)?)'
        posts=r'/(?:tasks(?:/[a-f0-9]{32}/(?:cancel|resume|archive-workspace))?|model-profiles|model-benchmark|memory)'
        if not ((handler.command=='GET' and re.fullmatch(gets,suffix)) or (handler.command=='POST' and re.fullmatch(posts,suffix))):
            handler.json_response({'error':'Route not allowed'},404);return True
        body=None
        if handler.command=='POST':
            length=int(handler.headers.get('Content-Length','0'))
            if not 0<=length<=512000:raise ValueError('Request too large')
            body=handler.rfile.read(length) or b'{}'
        query=urlencode(parse_qsl(parsed.query,keep_blank_values=True))
        req=Request(core_url+'/agent40'+suffix+('?' +query if query else ''),body,headers,method=handler.command)
        try:
            with opener.open(req,timeout=20) as r:
                if suffix.endswith('/screenshot.png'):
                    payload=r.read(8_000_000);handler.send_response(200);handler.send_header('Content-Type','image/png');handler.send_header('Content-Length',str(len(payload)));handler.send_header('Cache-Control','no-store');handler.end_headers();handler.wfile.write(payload)
                else:handler.json_response(json.loads(r.read(8_000_000)),r.status)
        except HTTPError as exc:
            data=json.loads(exc.read(64000));handler.json_response({'error':data.get('detail',data)},exc.code)
    except Exception as exc:handler.json_response({'error':str(exc)},503)
    return True


def stream_message(handler,core_url,opener,headers):
    if handler.command!='POST':handler.json_response({'error':'POST required'},405);return
    app=sys.modules[handler.__class__.__module__];data=handler.body();cid=str(data.get('conversation_id',''))
    if not re.fullmatch('[a-f0-9]{32}',cid):raise ValueError('Неверный ID чата')
    with app.connect() as db:
        if not db.execute('SELECT id FROM conversations WHERE id=?',(cid,)).fetchone():raise ValueError('Чат не найден')
    text=str(data.get('text','')).strip();image=None;regenerate=bool(data.get('regenerate'))
    if not regenerate:
        if data.get('image'):
            encoded=data['image']
            if not isinstance(encoded,str) or len(encoded)>app.MAX_IMAGE*2 or ',' not in encoded:raise ValueError('Неверное изображение')
            media,blob=encoded.split(',',1);allowed={'data:image/png;base64':'.png','data:image/jpeg;base64':'.jpg','data:image/webp;base64':'.webp'}
            if media not in allowed:raise ValueError('Поддерживаются PNG, JPEG и WEBP')
            raw=base64.b64decode(blob,validate=True)
            if len(raw)>app.MAX_IMAGE:raise ValueError('Изображение больше 10 МБ')
            image=uuid.uuid4().hex+allowed[media];(app.IMAGES/image).write_bytes(raw)
        if not text and not image:raise ValueError('Пустое сообщение')
        with app.connect() as db:
            db.execute('INSERT INTO messages(id,conversation_id,role,content,image_filename) VALUES(?,?,?,?,?)',(uuid.uuid4().hex,cid,'user',text,image))
    else:
        with app.connect() as db:
            row=db.execute('SELECT id,role,content FROM messages WHERE conversation_id=? ORDER BY rowid DESC LIMIT 1',(cid,)).fetchone()
            if row and row['role']=='assistant':
                db.execute('CREATE TABLE IF NOT EXISTS message_versions(id TEXT,conversation_id TEXT,content TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP)')
                db.execute('INSERT INTO message_versions(id,conversation_id,content) VALUES(?,?,?)',(row['id'],cid,row['content']))
                db.execute('DELETE FROM messages WHERE id=?',(row['id'],))
    with app.connect() as db:db.execute('UPDATE conversations SET updated=CURRENT_TIMESTAMP WHERE id=?',(cid,))
    if not app.core_healthy():app.start_core()
    payload={'messages':app.core_messages(cid,app.settings_get()),'session_id':cid,'project':str(data.get('project','.') or '.'),
             'model':str(data.get('model','auto')),'allow_tests':bool(data.get('allow_tests',False)),
             'test_consent':'EXECUTE_TRUSTED_PROJECT' if data.get('allow_tests') else '', 'backend':str(data.get('backend','native'))}
    request=Request(core_url+'/agent40/dialogue/stream',json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers,method='POST')
    response=opener.open(request,timeout=420)
    handler.send_response(200);handler.send_header('Content-Type','text/event-stream; charset=utf-8');handler.send_header('Cache-Control','no-store');handler.send_header('Connection','close');handler.end_headers()
    answer='';done=None;disconnected=False
    try:
        for line in response:
            if line.startswith(b'data: '):
                event=json.loads(line[6:].decode('utf-8'))
                if event.get('type')=='token':answer+=event.get('content','')
                if event.get('type')=='done':done=event;continue
            handler.wfile.write(line);handler.wfile.flush()
    except (BrokenPipeError,ConnectionResetError):
        disconnected=True
        try:opener.open(Request(core_url+'/agent40/dialogue/'+cid+'/cancel',b'{}',headers,method='POST'),timeout=3).close()
        except Exception:pass
    except Exception as exc:
        done={'type':'done','data':{'interrupted':True}}
        try:
            handler.wfile.write(('data: '+json.dumps({'type':'error','data':{'message':'Поток ответа прерван: '+str(exc)[:200]}},ensure_ascii=False)+'\n\n').encode('utf-8'));handler.wfile.flush()
        except (BrokenPipeError,ConnectionResetError):disconnected=True
    finally:
        response.close()
        if answer:
            if disconnected or (done and (done.get('data',{}).get('cancelled') or done.get('data',{}).get('interrupted'))):answer+='\n\n[Генерация остановлена]'
            with app.connect() as db:
                db.execute('INSERT INTO messages(id,conversation_id,role,content) VALUES(?,?,?,?)',(uuid.uuid4().hex,cid,'assistant',answer))
                db.execute('UPDATE conversations SET updated=CURRENT_TIMESTAMP WHERE id=?',(cid,))
    if not disconnected:
        handler.wfile.write(('data: '+json.dumps(done or {'type':'done','data':{}},ensure_ascii=False)+'\n\n').encode('utf-8'));handler.wfile.flush()
