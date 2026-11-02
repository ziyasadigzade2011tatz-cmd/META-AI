"""META Desktop 1.3: local desktop application with embedded Qt WebEngine."""
from __future__ import annotations
import base64
import hashlib
import hmac
import secrets
import zipfile
import io
import json
import mimetypes
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, parse_qs
from http.cookies import SimpleCookie
from urllib.request import Request, urlopen

FROZEN = bool(getattr(sys, 'frozen', False))
APP = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
STATIC_ROOT = Path(getattr(sys, '_MEIPASS', APP))
DATA = Path(os.environ.get('LOCALAPPDATA', str(APP))) / 'META Desktop' if FROZEN else APP / 'data'
DATA.mkdir(exist_ok=True)
IMAGES = DATA / 'images'
IMAGES.mkdir(exist_ok=True)
DB = DATA / 'meta_desktop.db'
CORE_DIR = Path(r'D:\META\Core')
CORE_PYTHON = CORE_DIR / '.venv' / 'Scripts' / 'python.exe'
CORE_URL = 'http://127.0.0.1:8000'
PORT = 8767
MAX_IMAGE = 10 * 1024 * 1024
CORE_PROCESS = None

DEFAULT_SETTINGS = {'theme':'dark','accent':'amber','density':'compact','font_size':'normal',
    'display_name':'','assistant_name':'META','language':'ru','custom_instructions':'',
    'show_tips':True,'response_style':'balanced','start_screen':'actions','reduce_motion':False}
ACCOUNT_DB = DATA / 'account.db'
SESSIONS = {}
SESSION_LOCK = threading.Lock()

def auth_db():
    db=sqlite3.connect(ACCOUNT_DB, timeout=10)
    db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS local_account (id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL, email TEXT, salt TEXT NOT NULL, hash TEXT NOT NULL)')
    db.commit()
    return db

def account_state():
    with auth_db() as db:
        row=db.execute('SELECT name,email FROM local_account WHERE id=1').fetchone()
        return dict(row) if row else None

def password_hash(password,salt):
    return hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),bytes.fromhex(salt),310000).hex()



def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=15000')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS conversations (
      id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP,
      updated TEXT DEFAULT CURRENT_TIMESTAMP, pinned INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS messages (
      id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
      content TEXT NOT NULL, image_filename TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',updated TEXT DEFAULT CURRENT_TIMESTAMP);
    ''')
    columns = [r[1] for r in db.execute('PRAGMA table_info(conversations)')]
    if 'mode' not in columns:
        db.execute("ALTER TABLE conversations ADD COLUMN mode TEXT NOT NULL DEFAULT 'chat'")
    db.commit()
    return db


def settings_get():
    with connect() as db:
        values = dict(DEFAULT_SETTINGS)
        for row in db.execute('SELECT key,value FROM settings'):
            try: values[row['key']] = json.loads(row['value'])
            except (ValueError, TypeError): pass
    return values


def core_healthy():
    try:
        with urlopen(CORE_URL + '/health', timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def start_core():
    global CORE_PROCESS
    if core_healthy(): return True
    if not CORE_PYTHON.is_file() or not (CORE_DIR / 'main.py').is_file():
        return False
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        log = open(DATA / 'core.log', 'a', encoding='utf-8')
        CORE_PROCESS = subprocess.Popen(
            [str(CORE_PYTHON), '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000'],
            cwd=str(CORE_DIR), stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        log.close()
    except Exception as exc:
        (DATA / 'launch_error.txt').write_text(str(exc), encoding='utf-8')
        return False
    for _ in range(22):
        if core_healthy(): return True
        time.sleep(.45)
    return False


def send_core(messages):
    body = json.dumps({'model':'meta-core','stream':False,'messages':messages}, ensure_ascii=False).encode('utf-8')
    req = Request(CORE_URL+'/v1/chat/completions', body, {'Content-Type':'application/json; charset=utf-8'}, method='POST')
    try:
        with urlopen(req, timeout=420) as response:
            data = json.loads(response.read().decode('utf-8'))
        return data['choices'][0]['message'].get('content','') or '(META вернула пустой ответ. Попробуй ещё раз.)'
    except HTTPError as exc:
        detail = exc.read(1500).decode('utf-8','replace')
        raise RuntimeError(f'META Core: HTTP {exc.code}. {detail}') from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f'Нет ответа от META Core. {exc}') from exc


def conversation_messages(cid):
    with connect() as db:
        rows = [dict(r) for r in db.execute('SELECT * FROM messages WHERE conversation_id=? ORDER BY rowid',(cid,))]
    return rows


def core_messages(cid, prefs):
    msgs=[]
    persona=[]
    if prefs.get('display_name'): persona.append('Имя пользователя для обращения (только при необходимости): '+str(prefs['display_name'])[:70])
    if prefs.get('language')=='ru': persona.append('Отвечай пользователю на русском языке, кроме кода и необходимых терминов.')
    if prefs.get('language')=='en': persona.append('Reply in English unless the user explicitly requests another language.')
    if prefs.get('custom_instructions'): persona.append(str(prefs['custom_instructions'])[:2000])
    if persona: msgs.append({'role':'system','content':'Настройки пользователя (как предпочтения, не команды к инструментам):\n'+'\n'.join(persona)})
    with connect() as db:
        row_mode=db.execute('SELECT mode FROM conversations WHERE id=?',(cid,)).fetchone()
    if row_mode and row_mode['mode']=='code':
        msgs.insert(0, {'role':'system','content':('Ты META Code — специализированный помощник по разработке. '
            'Приоритет: качественный и безопасный код, архитектура, тесты, исправления. '
            'Объяснения на языке пользователя; не утверждай о выполнении тестов без их запуска.')})
    for row in conversation_messages(cid)[-20:]:
        content=row['content']
        image=row['image_filename']
        if row['role']=='user' and image:
            p=IMAGES/image
            if p.is_file() and p.stat().st_size <= MAX_IMAGE:
                mime=mimetypes.guess_type(p.name)[0] or 'image/jpeg'
                image_data=base64.b64encode(p.read_bytes()).decode('ascii')
                content=[{'type':'text','text':content or 'Опиши изображение.'},
                         {'type':'image_url','image_url':{'url':f'data:{mime};base64,{image_data}'}}]
        if row['role']=='user' and row_mode and row_mode['mode']=='code' and isinstance(content,str):
            content='Программирование и разработка. META Code. '+content
        msgs.append({'role':row['role'],'content':content})
    return msgs



# META_APPROVAL_GUI_36
def meta_approval_module():
    import sys
    core_path = str(CORE_DIR)
    if core_path not in sys.path:
        sys.path.insert(0, core_path)
    import agent_pending
    return agent_pending

class Handler(BaseHTTPRequestHandler):
    server_version='META/1.3'
    def log_message(self,*args): return

    def authorized(self):
        if not account_state(): return True
        cookies=SimpleCookie()
        try: cookies.load(self.headers.get('Cookie',''))
        except Exception: return False
        token=cookies.get('meta_session')
        if not token: return False
        with SESSION_LOCK: return token.value in SESSIONS

    def auth_guard(self):
        if not self.authorized():
            self.json_response({'error':'Требуется вход в локальную учётную запись','auth_required':True},401)
            return False
        return True

    def same_origin(self):
        origin=self.headers.get('Origin')
        return not origin or origin in (f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}')

    def account_reply(self,success=False):
        item=account_state()
        return {'configured':bool(item),'signed_in':self.authorized(),
                'name':item['name'] if item else None,
                'email':item['email'] if item else None,
                'email_verified':False,'email_codes_enabled':False}


    def json_response(self, data, status=200):
        b=json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; font-src 'self'")
        self.send_header('Content-Length',str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def auth_set_cookie(self, token, logout=False):
        account=self.account_reply();account['signed_in']=not logout
        result=json.dumps({'ok':True,'account':account},ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Set-Cookie','meta_session='+token+'; HttpOnly; SameSite=Strict; Path=/'+('; Max-Age=0' if logout else ''))
        self.send_header('Content-Length',str(len(result)))
        self.end_headers();self.wfile.write(result)

    def static(self, rel, content_type):
        p=STATIC_ROOT/rel
        if not p.is_file(): return self.json_response({'error':'not found'},404)
        b=p.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type',content_type)
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; font-src 'self'")
        self.send_header('Content-Length',str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        length=int(self.headers.get('Content-Length','0'))
        if length>16*1024*1024: raise ValueError('Размер запроса больше 16 МБ')
        if length<1: return {}
        return json.loads(self.rfile.read(length).decode('utf-8'))

    def do_GET(self):
        # META40_DESKTOP_INTEGRATION
        from meta40_desktop import handle as handle_meta40
        if handle_meta40(self, CORE_DIR, CORE_URL, PORT, bool(account_state())):
            return
        parsed=urlsplit(self.path)
        p=parsed.path
        try:
            if p=='/': return self.static('assets/index.html','text/html; charset=utf-8')
            if p=='/app.css': return self.static('assets/app.css','text/css; charset=utf-8')
            if p=='/app.js': return self.static('assets/app.js','text/javascript; charset=utf-8')
            if p=='/meta-icon.svg': return self.static('assets/meta-icon.svg','image/svg+xml')
            if p=='/api/status': return self.json_response({'core':core_healthy(),'version':'1.3','platform':'Windows'})
            if p=='/api/account': return self.json_response(self.account_reply())
            if p.startswith('/api/') and not self.auth_guard(): return
            # META_APPROVAL_GUI_36
            if p.startswith('/api/proposals/'):
                if not account_state() or not self.authorized():
                    return self.json_response({'error':'Login required for approvals'},403)
                proposal_id = p.split('/')[-1]
                try:
                    return self.json_response(meta_approval_module().proposal_preview(proposal_id))
                except (ValueError, RuntimeError, OSError, KeyError) as exc:
                    return self.json_response({'error':str(exc)},409)
            if p=='/api/notes':
                with connect() as db: rows=[dict(x) for x in db.execute('SELECT * FROM notes ORDER BY updated DESC')]
                return self.json_response(rows)
            if p=='/api/export':
                with connect() as db:
                    chats=[dict(x) for x in db.execute('SELECT * FROM conversations')]
                    msgs=[dict(x) for x in db.execute('SELECT * FROM messages')]
                    notes=[dict(x) for x in db.execute('SELECT * FROM notes')]
                payload=json.dumps({'conversations':chats,'messages':msgs,'notes':notes,'settings':settings_get()},ensure_ascii=False,indent=2).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Disposition','attachment; filename="meta-export.json"')
                self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(payload)))
                self.end_headers();self.wfile.write(payload);return
            if p=='/api/workspace':
                try:
                    with urlopen(CORE_URL+'/agent/files',timeout=5) as r:
                        return self.json_response(json.loads(r.read().decode('utf-8')))
                except Exception as err: return self.json_response({'error':str(err)},503)

            if p=='/api/settings': return self.json_response(settings_get())
            if p=='/api/chats':
                with connect() as db:
                    rows=[dict(r) for r in db.execute('SELECT * FROM conversations ORDER BY pinned DESC,updated DESC')]
                return self.json_response(rows)
            if p.startswith('/api/chats/') and p.endswith('/messages'):
                cid=p.split('/')[3]
                return self.json_response(conversation_messages(cid))
            if p.startswith('/api/image/'):
                filename=p.split('/')[-1]
                if not filename or filename!=Path(filename).name: return self.json_response({'error':'Invalid'},400)
                image=IMAGES/filename
                if not image.is_file(): return self.json_response({'error':'Image missing'},404)
                raw=image.read_bytes()
                mime=mimetypes.guess_type(image.name)[0] or 'application/octet-stream'
                self.send_response(200)
                self.send_header('Content-Type',mime)
                self.send_header('Content-Length',str(len(raw)))
                self.send_header('X-Content-Type-Options','nosniff')
                self.end_headers()
                self.wfile.write(raw)
                return
            if p=='/api/memories':
                try:
                    with urlopen(CORE_URL+'/memory',timeout=15) as resp:
                        return self.json_response(json.loads(resp.read().decode('utf-8')))
                except Exception as e: return self.json_response({'memories':[],'error':str(e)},503)
            return self.json_response({'error':'Not found'},404)
        except Exception as e:
            return self.json_response({'error':str(e)},500)

    def do_POST(self):
        # META40_DESKTOP_INTEGRATION
        from meta40_desktop import handle as handle_meta40
        if handle_meta40(self, CORE_DIR, CORE_URL, PORT, bool(account_state())):
            return
        p=urlsplit(self.path).path
        try:
            if not self.same_origin(): return self.json_response({'error':'Неверный источник запроса'},403)
            data=self.body()
            if p=='/api/account/register':
                if account_state(): return self.json_response({'error':'Локальная учётная запись уже существует'},409)
                name=str(data.get('name','')).strip()[:60]
                password=str(data.get('password',''))
                email=str(data.get('email','')).strip()[:160]
                if len(name)<2 or len(password)<8: return self.json_response({'error':'Имя от 2 символов, пароль от 8 символов'},400)
                salt=secrets.token_hex(16)
                try:
                    with auth_db() as db: db.execute('INSERT INTO local_account(id,name,email,salt,hash) VALUES (1,?,?,?,?)',(name,email,salt,password_hash(password,salt)))
                except sqlite3.IntegrityError: return self.json_response({'error':'Аккаунт уже существует'},409)
                token=secrets.token_urlsafe(32)
                with SESSION_LOCK: SESSIONS[token]=True
                return self.auth_set_cookie(token)
            if p=='/api/account/login':
                with auth_db() as db: account=db.execute('SELECT * FROM local_account WHERE id=1').fetchone()
                if not account: return self.json_response({'error':'Сначала создай учётную запись'},404)
                test=password_hash(str(data.get('password','')),account['salt'])
                if not hmac.compare_digest(test,account['hash']): return self.json_response({'error':'Неверный пароль'},403)
                token=secrets.token_urlsafe(32)
                with SESSION_LOCK: SESSIONS[token]=True
                return self.auth_set_cookie(token)
            if p=='/api/account/logout':
                cookies=SimpleCookie()
                try: cookies.load(self.headers.get('Cookie',''))
                except Exception: pass
                session=cookies.get('meta_session')
                if session:
                    with SESSION_LOCK: SESSIONS.pop(session.value,None)
                return self.auth_set_cookie('',logout=True)
            if p.startswith('/api/') and not self.auth_guard(): return
            # META_APPROVAL_GUI_36
            if p.startswith('/api/proposals/'):
                if not account_state() or not self.authorized():
                    return self.json_response({'error':'Login required for approvals'},403)
                if self.headers.get('Origin') not in (f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'):
                    return self.json_response({'error':'Explicit same-origin approval required'},403)
                parts = p.strip('/').split('/')
                if len(parts) != 4 or parts[:2] != ['api', 'proposals']:
                    return self.json_response({'error':'Bad proposal path'},400)
                proposal_id, action = parts[2], parts[3]
                try:
                    engine = meta_approval_module()
                    if action == 'apply':
                        return self.json_response(engine.proposal_approve(proposal_id))
                    if action == 'reject':
                        return self.json_response(engine.proposal_reject(proposal_id))
                    return self.json_response({'error':'Unknown action'},400)
                except (ValueError, RuntimeError, OSError, KeyError) as exc:
                    return self.json_response({'error':str(exc)},409)
            if p=='/api/notes':
                nid=str(data.get('id') or uuid.uuid4().hex)
                title=str(data.get('title','Без названия')).strip()[:160]
                body=str(data.get('body',''))[:100000]
                with connect() as db: db.execute('INSERT INTO notes(id,title,body,updated) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(id) DO UPDATE SET title=excluded.title,body=excluded.body,updated=CURRENT_TIMESTAMP',(nid,title,body))
                return self.json_response({'id':nid,'ok':True})
            if p=='/api/settings':
                validated=dict(DEFAULT_SETTINGS)
                validated.update({k:data[k] for k in DEFAULT_SETTINGS if k in data})
                if validated['theme'] not in ('dark','light','system'): validated['theme']='dark'
                if validated['accent'] not in ('violet','blue','graphite','amber','black','mono'): validated['accent']='amber'
                if validated['density'] not in ('comfortable','compact'): validated['density']='comfortable'
                if validated['font_size'] not in ('small','normal','large'): validated['font_size']='normal'
                if validated['language'] not in ('auto','ru','en'): validated['language']='auto'
                validated['custom_instructions']=str(validated['custom_instructions'])[:2000]
                validated['display_name']=str(validated['display_name'])[:70]
                validated['assistant_name']=str(validated['assistant_name'])[:40]
                if validated['response_style'] not in ('balanced','concise','detailed','friendly'): validated['response_style']='balanced'
                if validated['start_screen'] not in ('actions','minimal'): validated['start_screen']='actions'
                validated['reduce_motion']=bool(validated['reduce_motion'])
                validated['show_tips']=bool(validated['show_tips'])
                with connect() as db:
                    for key,value in validated.items():
                        db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)', (key,json.dumps(value,ensure_ascii=False)))
                return self.json_response(validated)
            if p=='/api/chats':
                cid=uuid.uuid4().hex
                title=str(data.get('title') or 'Новый чат')[:90]
                mode='code' if data.get('mode')=='code' else 'chat'
                with connect() as db:
                    db.execute('INSERT INTO conversations(id,title,mode) VALUES (?,?,?)',(cid,title,mode))
                return self.json_response({'id':cid,'title':title,'mode':mode})
            if p.startswith('/api/chats/') and p.endswith('/rename'):
                cid=p.split('/')[3]
                title=str(data.get('title','')).strip()[:90]
                if not title: return self.json_response({'error':'Empty title'},400)
                with connect() as db: db.execute('UPDATE conversations SET title=? WHERE id=?',(title,cid))
                return self.json_response({'ok':True})
            if p.startswith('/api/chats/') and p.endswith('/pin'):
                cid=p.split('/')[3]
                with connect() as db: db.execute('UPDATE conversations SET pinned=? WHERE id=?',(int(bool(data.get('pinned'))),cid))
                return self.json_response({'ok':True})
            if p=='/api/message':
                cid=str(data.get('conversation_id',''))
                text=str(data.get('text','')).strip()
                encoded=data.get('image')
                image_filename=None
                if encoded:
                    if not isinstance(encoded,str) or not encoded.startswith('data:image/') or ';base64,' not in encoded:
                        return self.json_response({'error':'Only base64 images supported'},400)
                    media,blob=encoded.split(',',1)
                    allowed={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}
                    mime=media.split(';')[0][5:]
                    if mime not in allowed: return self.json_response({'error':'Supported: PNG, JPG, WEBP'},400)
                    if len(blob)>MAX_IMAGE*2: return self.json_response({'error':'Image too large'},400)
                    raw=base64.b64decode(blob,validate=True)
                    if len(raw)>MAX_IMAGE: return self.json_response({'error':'Image too large'},400)
                    image_filename=uuid.uuid4().hex+allowed[mime]
                    (IMAGES/image_filename).write_bytes(raw)
                if not text and not image_filename: return self.json_response({'error':'Empty message'},400)
                with connect() as db:
                    if not db.execute('SELECT id FROM conversations WHERE id=?',(cid,)).fetchone():
                        return self.json_response({'error':'Chat missing'},404)
                    mid=uuid.uuid4().hex
                    db.execute('INSERT INTO messages(id,conversation_id,role,content,image_filename) VALUES (?, ?, ?, ?, ?)',(mid,cid,'user',text,image_filename))
                    db.execute('UPDATE conversations SET updated=CURRENT_TIMESTAMP WHERE id=?',(cid,))
                if not core_healthy(): start_core()
                if not core_healthy(): return self.json_response({'error':'META Core недоступен. Проверь D:\\META\\Core и Ollama. Сообщение сохранено.'},503)
                reply=send_core(core_messages(cid,settings_get()))
                with connect() as db:
                    mid=uuid.uuid4().hex
                    db.execute('INSERT INTO messages(id,conversation_id,role,content) VALUES (?, ?, ?, ?)',(mid,cid,'assistant',reply))
                    db.execute('UPDATE conversations SET updated=CURRENT_TIMESTAMP WHERE id=?',(cid,))
                return self.json_response({'reply':reply})
            return self.json_response({'error':'Not found'},404)
        except Exception as exc:
            return self.json_response({'error':str(exc)},500)

    def do_DELETE(self):
        p=urlsplit(self.path).path
        try:
            if not self.same_origin(): return self.json_response({'error':'Неверный источник запроса'},403)
            if not self.auth_guard(): return
            if p.startswith('/api/notes/'):
                with connect() as db: db.execute('DELETE FROM notes WHERE id=?',(p.split('/')[-1],))
                return self.json_response({'ok':True})
            if p=='/api/chats':
                with connect() as db: db.execute('DELETE FROM conversations')
                return self.json_response({'ok':True})
            if p.startswith('/api/chats/'):
                cid=p.split('/')[3]
                with connect() as db: db.execute('DELETE FROM conversations WHERE id=?',(cid,))
                return self.json_response({'ok':True})
            if p.startswith('/api/memories/'):
                memory_id=p.split('/')[-1]
                if not memory_id.isdigit(): return self.json_response({'error':'Invalid ID'},400)
                req=Request(CORE_URL+'/memory/'+memory_id,method='DELETE')
                with urlopen(req,timeout=15) as r: return self.json_response(json.loads(r.read().decode('utf-8')))
            return self.json_response({'error':'Not found'},404)
        except Exception as e: return self.json_response({'error':str(e)},500)


def ui_running():
    """Check only the META UI HTTP server on its actual configured port."""
    try:
        with urlopen(f'http://127.0.0.1:{PORT}/api/status', timeout=1) as response:
            payload = json.loads(response.read().decode('utf-8'))
            return payload.get('platform') == 'Windows' and payload.get('version') == '1.3'
    except Exception:
        return False


def main():
    """Native desktop window (not an external Chrome/Edge app window)."""
    # Software rendering is safer for hybrid GPU flicker. Opt in to GPU with META_GPU=1.
    if os.environ.get('META_GPU') == '0':
        flags = os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '')
        for switch in ('--disable-gpu', '--disable-gpu-compositing', '--disable-accelerated-2d-canvas'):
            if switch not in flags:
                flags += ' ' + switch
        os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = flags.strip()
    try:
        from PySide6.QtCore import QUrl, Qt
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication, QMainWindow
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEngineProfile
    except ImportError as exc:
        raise RuntimeError(
            'Для META 1.3 нужен встроенный Qt WebEngine. '
            'Один раз запусти Install_META_1_3.cmd, затем META.exe. '
            f'Подробности: {exc}'
        ) from exc

    connect().close()
    if not ui_running():
        server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
    threading.Thread(target=start_core,daemon=True).start()

    app=QApplication(sys.argv)
    app.setApplicationName('META')
    icon_path=STATIC_ROOT/'assets'/'meta.ico'
    if icon_path.is_file(): app.setWindowIcon(QIcon(str(icon_path)))

    window=QMainWindow()
    window.setWindowTitle('META')
    window.setMinimumSize(820,570)
    window.resize(1290,840)
    if icon_path.is_file(): window.setWindowIcon(QIcon(str(icon_path)))
    view=QWebEngineView(window)
    window.setCentralWidget(view)
    profile=QWebEngineProfile.defaultProfile()
    profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)

    def save_download(item):
        from PySide6.QtWidgets import QFileDialog
        dest,_=QFileDialog.getSaveFileName(window,'Сохранить экспорт',item.downloadFileName(),'JSON (*.json);;Все файлы (*)')
        if dest:
            parent=Path(dest).parent
            item.setDownloadDirectory(str(parent))
            item.setDownloadFileName(Path(dest).name)
            item.accept()
        else:
            item.cancel()
    profile.downloadRequested.connect(save_download)
    view.page().newWindowRequested.connect(lambda request: webbrowser.open(request.requestedUrl().toString()) if request.requestedUrl().scheme() == 'https' else None)
    view.setUrl(QUrl(f'http://127.0.0.1:{PORT}/'))
    window.show()
    return app.exec()


if __name__=='__main__':
    try: main()
    except Exception as exc:
        (DATA/'desktop_error.txt').write_text(str(exc),encoding='utf-8')
        if os.name=='nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,str(exc),'META Desktop 1.3',0x10)
        raise
