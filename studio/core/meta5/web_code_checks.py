"""Static HTML dependency checks; does not execute project JavaScript."""
import posixpath,re
from html.parser import HTMLParser
from urllib.parse import urlsplit,unquote

class Page(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.links=[];self.tags=[];self.headings=[];self.heading=None
    def handle_starttag(self,tag,attrs):
        self.tags.append(tag);attrs=dict(attrs)
        if tag in ('title','h1'):self.heading=tag;self.headings.append('')
        if tag=='script' and attrs.get('src'):self.links.append(attrs['src'])
        if tag=='link' and 'stylesheet' in attrs.get('rel','') and attrs.get('href'):self.links.append(attrs['href'])
    def handle_endtag(self,tag):
        if tag==self.heading:self.heading=None
    def handle_data(self,data):
        if self.heading:self.headings[-1]+=data

def brief_check(text,brief):
    if not brief.get('website'):return []
    page=Page();page.feed(text);problems=[]
    if brief.get('web_requested') and any(re.search(r'web[ _-]*search(?:ing)?',h,re.I) for h in page.headings) and not brief.get('product_name'):
        problems.append('Служебная команда поиска попала в заголовок продукта. Убери её, сохранив цель задачи.')
    if not brief.get('product_name'):
        references={r.casefold().strip() for r in brief.get('reference_targets',[])}
        if any(h.casefold().strip() in references for h in page.headings):problems.append('Имя референса стало названием продукта без явного запроса. Используй самостоятельное рабочее название.')
    return problems

def javascript(text):
    import os,shutil,subprocess
    from pathlib import Path
    node=shutil.which('node')
    if not node and Path('D:/META/Tools/node.exe').is_file():node='D:/META/Tools/node.exe'
    if not node:return {'status':'not_run','scope':'JavaScript syntax: Node.js не установлен'}
    env={k:v for k,v in os.environ.items() if k.upper() not in ('NODE_OPTIONS','NODE_PATH')}
    try:
        result=subprocess.run([node,'--check','--input-type=module'],input=text,text=True,encoding='utf-8',capture_output=True,timeout=5,env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        return {'status':'passed' if result.returncode==0 else 'failed','scope':'Node.js syntax only; code not executed','error':result.stderr[-1200:] if result.returncode else ''}
    except (OSError,subprocess.TimeoutExpired):return {'status':'not_run','scope':'JavaScript syntax checker unavailable'}

def check(name,text,files,project=None):
    page=Page();page.feed(text);problems=[]
    for url in page.links:
        parsed=urlsplit(url)
        if parsed.scheme or parsed.netloc or not parsed.path:continue
        path=posixpath.normpath(posixpath.join(posixpath.dirname(name),unquote(parsed.path)))
        if path.startswith('/') or path=='..' or path.startswith('../'):
            problems.append('Ресурс выходит за проект: '+url);continue
        if path in files:continue
        try:exists=project is not None and project.path(path).is_file()
        except ValueError:exists=False
        if not exists:problems.append('Не найден подключённый ресурс: '+path)
    return problems
