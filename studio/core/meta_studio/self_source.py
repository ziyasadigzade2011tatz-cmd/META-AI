"""Own-source reading and a separate Git development workspace; no live writes."""
import hashlib,json,os,shutil,subprocess,uuid
from pathlib import Path
from meta5.project import linked,parts

class SelfSource:
    def __init__(self,core=None,source=None):
        self.core=Path(core or Path(__file__).resolve().parents[1]).resolve()
        self.source=Path(source or self.core.parent/'source').resolve()
    def files(self):
        out={}
        for folder in ('meta5','meta40','meta_studio'):
            root=self.core/folder
            if root.is_dir():
                for p in root.rglob('*.py'):
                    if any(any(word in part.lower() for word in ('secret','credential','token')) or part.endswith('_state') for part in p.relative_to(self.core).parts):continue
                    if '__pycache__' not in p.parts and not any(linked(v) for v in [p,*list(p.parents)[:len(p.relative_to(self.core).parts)-1]]):out['core/'+p.relative_to(self.core).as_posix()]=p
        root_sources=[p.name for p in self.core.glob('*.py') if not any(w in p.name.lower() for w in ('secret','credential','token'))]
        defaults=['config/'+name for name in ('system.md','agent.json','domains.json','memory.json','models.json','performance.json','search.json','slang.json','understanding.json')]
        for name in (*root_sources,'requirements.txt','meta5_models_seed.json',*defaults):
            p=self.core/name
            if p.is_file() and not linked(p):out['core/'+name]=p
        folder=self.core/'config/coding'
        if folder.is_dir():
            for p in folder.iterdir():
                if p.suffix in ('.md','.json') and not linked(p):out['core/'+p.relative_to(self.core).as_posix()]=p
        if self.source.is_dir():
            for p in self.source.rglob('*'):
                if not p.is_file() or p.suffix not in ('.ts','.js','.css','.html','.json','.md','.py','.cs') or linked(p):continue
                rel=p.relative_to(self.source)
                if any(v in ('node_modules','.git','__pycache__') or v.endswith('_state') for v in rel.parts):continue
                if any(v in p.name.lower() for v in ('secret','credential','token','preferences','meta40_config')):continue
                if any(linked(v) for v in p.parents if v!=self.source and self.source in v.parents):continue
                out[rel.as_posix()]=p
        return out
    def index(self):
        return {'files':[{'path':name,'bytes':p.stat().st_size} for name,p in sorted(self.files().items())],
                'access':'read_only','live_write_allowed':False}
    def read(self,name,start=1,end=100):
        if not isinstance(name,str):raise ValueError('Укажи путь из списка исходников')
        parts(name);p=self.files().get(name)
        if not p:raise ValueError('Файл не входит в доступные исходники META')
        raw=p.read_bytes()
        if len(raw)>500000:raise ValueError('Файл слишком большой для чтения')
        lines=raw.decode('utf-8-sig').splitlines();start=max(1,int(start));end=min(len(lines),max(start,min(int(end),start+199)))
        return {'path':name,'start':start,'end':end,'total_lines':len(lines),'content':'\n'.join(lines[start-1:end]),
                'sha256':hashlib.sha256(raw).hexdigest(),'read_only':True,'truncated':start>1 or end<len(lines)}
    def workspace(self,projects,approved=False):
        if approved is not True:raise ValueError('Подтверди создание отдельного проекта для правок')
        git=shutil.which('git')
        if not git:raise ValueError('Для саморазработки нужен установленный Git')
        from meta40.workspace import project_root
        name='meta-selfdev-'+uuid.uuid4().hex[:8];root=project_root(projects,name,create=True)
        files=self.files();manifest={}
        for relative,path in files.items():
            raw=path.read_bytes()
            if len(raw)>500000:continue
            target=root.joinpath(*parts(relative));target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            manifest[relative]=hashlib.sha256(raw).hexdigest()
        (root/'META_SOURCE_MANIFEST.json').write_text(json.dumps({'version':1,'files':manifest,'live_install_modified':False},indent=2)+'\n',encoding='utf-8')
        (root/'.gitignore').write_text('__pycache__/\n*.pyc\n*.sqlite*\n*.db\n*_state/\n.venv/\nnode_modules/\n.env\n*secret*\n*token*\nmeta40_config.json\n',encoding='utf-8')
        def run(*args):
            r=subprocess.run([git,'-C',str(root),'-c','core.hooksPath=.git/disabled-hooks','-c','commit.gpgSign=false',*args],capture_output=True,text=True,timeout=20,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            if r.returncode:raise ValueError('Не удалось создать Git-снимок проекта; рабочая META не изменена')
            return r.stdout.strip()
        run('init');run('config','user.name','META Local');run('config','user.email','meta@localhost')
        run('add','.');run('commit','-m','META self-development baseline');commit=run('rev-parse','HEAD')
        return {'project':name,'files':len(manifest),'commit':commit,'live_install_modified':False,
                'workflow':'Правки в проекте → diff → проверки → отдельная сборка и подтверждённая установка. Рабочая META не переписывается на ходу.'}
