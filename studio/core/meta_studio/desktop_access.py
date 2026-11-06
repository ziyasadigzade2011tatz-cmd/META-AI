"""One-use, per-action desktop approval. No background watching or automatic clicks."""
import json,os,subprocess,threading,time,uuid
from pathlib import Path

class DesktopAccess:
    def __init__(self,bridge=None,runner=None):
        self.bridge=Path(bridge or Path(__file__).resolve().parents[2]/'native/Meta.DesktopBridge.exe')
        self.runner=runner or self._run;self.pending={};self.lock=threading.RLock()
    def _run(self,*args):
        if os.name!='nt' or not self.bridge.is_file():raise ValueError('Нативный модуль Windows отсутствует в этой сборке')
        try:result=subprocess.run([str(self.bridge),*map(str,args)],capture_output=True,encoding='utf-8',timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:raise ValueError('Окно не ответило за 10 секунд; действие остановлено')
        try:data=json.loads(result.stdout)
        except ValueError:raise ValueError('Модуль Windows не вернул результат')
        if result.returncode or data.get('error'):
            message=str(data.get('error','Операция Windows не выполнена'))
            translations={'Restore the window before capture':'Разверни окно перед снимком',
                'Window does not support capture':'Это окно не разрешает снимок. Используй ручной скриншот',
                'Window returned an empty image; use a manual screenshot':'Окно вернуло пустое изображение. Используй ручной скриншот',
                'Window changed':'Окно изменилось; выбери его заново'}
            raise ValueError(translations.get(message,message)[:200])
        return data
    def windows(self):return self.runner('list')
    def request(self,action,target):
        if action not in ('capture','activate','launch'):raise ValueError('Недоступное действие')
        if action=='launch':
            p=Path(str(target))
            if not p.is_absolute() or p.suffix.lower()!='.exe' or not p.is_file() or str(p).startswith('\\\\') or p.is_symlink():raise ValueError('Укажи полный путь к локальному EXE без аргументов')
            info={'path':str(p.resolve()),'title':p.name,'size':p.stat().st_size,'modified':p.stat().st_mtime_ns}
        else:
            info=next((w for w in self.windows()['windows'] if w['id']==target),None)
            if not info:raise ValueError('Окно уже закрыто; обнови список')
            if any(s in (str(info.get('app',''))+' '+str(info.get('title',''))).lower() for s in ('keepass','1password','bitwarden','credentialuibroker','windows security','безопасность windows')):raise ValueError('Защищённое окно открывай вручную')
        with self.lock:
            self.pending={k:v for k,v in self.pending.items() if v['expires']>time.monotonic()}
            if len(self.pending)>=8:raise ValueError('Слишком много неподтверждённых действий')
            ident=uuid.uuid4().hex;self.pending[ident]={'action':action,'target':dict(info),'expires':time.monotonic()+60}
        return {'request_id':ident,'action':action,'target':info,'expires_in':60,'requires_approval':True}
    def approve(self,ident,approved=False):
        if approved is not True:raise ValueError('Нужно отдельное подтверждение действия')
        with self.lock:request=self.pending.pop(ident,None)
        if not request or request['expires']<time.monotonic():raise ValueError('Разрешение истекло или уже использовано')
        target=request['target'];action=request['action']
        if action=='launch':
            p=Path(target['path'])
            if not p.is_file() or p.stat().st_size!=target['size'] or p.stat().st_mtime_ns!=target['modified']:raise ValueError('Приложение изменилось; выбери его заново')
            subprocess.Popen([str(p)],cwd=p.parent,close_fds=True)
            return {'launched':True,'app':p.name}
        current=next((w for w in self.windows()['windows'] if w['id']==target['id']),None)
        if not current or any(current.get(k)!=target.get(k) for k in ('pid','title','app')):raise ValueError('Окно изменилось; требуется новое разрешение')
        return self.runner(action,target['id'],str(target['pid']))
