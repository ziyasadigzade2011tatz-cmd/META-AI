import ast
import hashlib
import json
import os
import re
from pathlib import Path,PureWindowsPath

TEXT={'.py','.js','.ts','.tsx','.jsx','.json','.toml','.yaml','.yml','.md','.txt','.html','.css','.csv','.lua','.ini','.cfg','.xml','.sql','.sh','.ps1','.cmd','.bat','.cs','.c','.h','.cpp','.rs'}
SKIP={'.git','.venv','venv','node_modules','__pycache__','.meta5','.meta40','dist','build'}
SPECIAL={'.gitignore','.editorconfig','.gitattributes'}
MAX_EDIT=256000


def digest(raw):return hashlib.sha256(raw).hexdigest() if raw is not None else None
def linked(p):
    return p.is_symlink() or bool(getattr(p.lstat(),'st_file_attributes',0)&0x400)


def parts(name):
    if not isinstance(name,str) or not name or len(name)>240:raise ValueError('Неверный путь')
    w=PureWindowsPath(name)
    if w.drive or w.root or '\\' in name:raise ValueError('Нужен относительный путь через /')
    out=name.split('/')
    for p in out:
        if p in ('','.','..') or p in SKIP or (p.startswith('.') and p not in SPECIAL and p!='.github') or re.search(r'[<>:"|?*\x00-\x1f]',p) or p.endswith((' ','.')):raise ValueError('Запрещённый путь: '+name)
        if p.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*('COM'+str(i) for i in range(1,10)),*('LPT'+str(i) for i in range(1,10))}:raise ValueError('Имя устройства запрещено')
        if re.search(r'(?i)(?:^|[_-])(?:secrets?|credentials?|passwords?)(?:[_.-]|$)',p):raise ValueError('Файл с секретами исключён')
    return out


class Project:
    def __init__(self,root):
        self.root=Path(root).absolute()
        if not self.root.is_dir():raise ValueError('Папка проекта не найдена: '+str(root))
        for p in [self.root,*self.root.parents]:
            if linked(p):raise ValueError('Связанные папки запрещены')
        self.root=self.root.resolve()

    def path(self,name,text_only=True):
        target=self.root.joinpath(*parts(name))
        for p in [target,*target.parents]:
            if p.is_symlink() or (p.exists() and linked(p)):raise ValueError('Ссылки и junction запрещены')
            if p==self.root:break
        if not target.resolve().is_relative_to(self.root):raise ValueError('Выход за проект запрещён')
        if text_only and target.suffix.lower() not in TEXT and target.name not in SPECIAL:raise ValueError('Неподдерживаемый текстовый файл')
        return target

    def files(self):
        out=[];folders=0
        for folder,dirs,names in os.walk(self.root,followlinks=False):
            folders+=1
            if folders>5000:raise ValueError('Слишком много папок в проекте')
            dirs[:]=sorted(d for d in dirs if d not in SKIP and (not d.startswith('.') or d=='.github') and not linked(Path(folder)/d))
            for name in sorted(names):
                rel=(Path(folder)/name).relative_to(self.root).as_posix()
                try:p=self.path(rel)
                except ValueError:continue
                if p.is_file():out.append({'path':rel,'bytes':p.stat().st_size})
                if len(out)>5000:raise ValueError('Бюджет проекта: 5000 текстовых файлов')
        return out

    def read(self,name,start=1,end=200):
        p=self.path(name)
        if p.stat().st_size>2_000_000:raise ValueError('Файл больше 2 МБ; раздели его для анализа')
        start=max(1,int(start));end=max(start,min(int(end),start+299))
        lines=p.read_text(encoding='utf-8-sig').splitlines()
        text='\n'.join(f'{i+1}: {line}' for i,line in enumerate(lines[start-1:end],start-1))
        return {'path':name,'start':start,'end':min(end,len(lines)),'total_lines':len(lines),'text':text[:24000],'truncated':len(text)>24000 or end<len(lines)}

    def search(self,query,limit=60):
        if not isinstance(query,str) or not 1<=len(query)<=200:raise ValueError('Поиск: 1–200 буквальных символов')
        matches=[];budget=0
        for entry in self.files():
            if entry['bytes']>2_000_000:continue
            budget+=entry['bytes']
            if budget>30_000_000:break
            try:lines=self.path(entry['path']).read_text(encoding='utf-8-sig').splitlines()
            except UnicodeError:continue
            for n,line in enumerate(lines,1):
                if query.casefold() in line.casefold():matches.append({'path':entry['path'],'line':n,'text':line[:400]})
                if len(matches)>=limit:return matches
        return matches

    def index(self):
        files=self.files();symbols=[];imports=[];manifests={};instructions=[]
        for entry in files:
            if entry['bytes']>MAX_EDIT:continue
            p=self.path(entry['path'])
            try:text=p.read_text(encoding='utf-8-sig')
            except UnicodeError:continue
            if p.name=='AGENTS.md':instructions.append({'path':entry['path'],'content':text[:5000]})
            if p.name in ('package.json','pyproject.toml','requirements.txt','Cargo.toml','tsconfig.json'):
                manifests[entry['path']]=text[:5000]
            if p.suffix=='.py':
                try:
                    tree=ast.parse(text)
                    for node in ast.walk(tree):
                        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                            symbols.append({'name':node.name,'kind':type(node).__name__,'path':entry['path'],'line':node.lineno,'end':node.end_lineno})
                        elif isinstance(node,(ast.Import,ast.ImportFrom)):
                            imports.append({'path':entry['path'],'module':getattr(node,'module',None) or ', '.join(n.name for n in node.names),'line':node.lineno})
                except SyntaxError:pass
            elif p.suffix in ('.js','.ts','.tsx','.jsx'):
                for n,line in enumerate(text.splitlines(),1):
                    m=re.search(r'\b(?:function|class|interface|type|const)\s+(\w+)',line)
                    if m:symbols.append({'name':m.group(1),'kind':'declaration','path':entry['path'],'line':n})
            if len(symbols)>1500:break
        languages={}
        for f in files:languages[Path(f['path']).suffix]=languages.get(Path(f['path']).suffix,0)+1
        return {'root':str(self.root),'files':files,'symbols':symbols[:1500],'imports':imports[:500],
                'manifests':manifests,'instructions_untrusted':instructions[:10],'languages':languages}

    def relevant(self,task,index=None):
        index=index or self.index();words=set(re.findall(r'[a-zA-Z_][a-zA-Z_0-9]{2,}',task.casefold()))
        ranking=[]
        for entry in index['files']:
            name=entry['path'];score=sum(w in name.casefold() for w in words)*3
            score+=sum(s['path']==name and s['name'].casefold() in words for s in index['symbols'])*5
            if name.endswith(('README.md','package.json','pyproject.toml')):score+=1
            ranking.append((score,name))
        return [name for _,name in sorted(ranking,reverse=True)[:8]]


def validate(name,content):
    parts(name)
    if not isinstance(content,str) or len(content.encode('utf-8'))>MAX_EDIT:raise ValueError('Лимит текста правки: 256 КБ')
    if name.endswith('.py'):ast.parse(content,filename=name)
    if name.endswith('.json'):json.loads(content)
