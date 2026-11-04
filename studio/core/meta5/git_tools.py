import json
import shutil
import subprocess
import sys
from pathlib import Path
from .storage import STATE
from .project import Project
from .process import run


def argv(root,*args):
    git=shutil.which('git')
    if not git:raise ValueError('Git не установлен')
    hooks=STATE/'empty_hooks';hooks.mkdir(parents=True,exist_ok=True)
    return [git,'-c','safe.directory='+str(Path(root).resolve()).replace('\\','/'),'-c','core.fsmonitor=false',
            '-c','core.hooksPath='+str(hooks),'-c','core.pager=cat','-c','diff.external=',
            '-c','protocol.file.allow=never','--no-pager',*args]


def command(root,*args,timeout=15):
    return run(argv(root,*args),root,timeout=timeout)


def inspect(root,action='status',path=None):
    if path:Project(root).path(path,text_only=False)
    options={'status':['status','--short','--untracked-files=normal'],
             'diff':['diff','--no-ext-diff','--no-textconv','--no-renames'],
             'log':['log','-8','--format=%h %s'],
             'branches':['branch','--list']}
    if action not in options:raise ValueError('Неизвестная Git-операция')
    args=options[action]
    if path and action=='diff':args+=['--',path]
    return command(root,*args)


def prepare(original,destination):
    """No checkout means repository smudge filters cannot execute on creation."""
    original=Path(original);destination=Path(destination)
    check=command(original,'rev-parse','--show-toplevel')
    same=check['exit_code']==0 and Path(check['output'].strip()).resolve()==original.resolve()
    if same:
        branch='meta/'+destination.name
        r=command(original,'worktree','add','--no-checkout','-b',branch,str(destination),'HEAD',timeout=30)
        if r['exit_code']!=0:raise ValueError('Не удалось создать Git worktree: '+r['output'][-1000:])
        r=command(destination,'read-tree','HEAD')
        if r['exit_code']!=0:raise ValueError('Не удалось подготовить индекс worktree')
        return {'kind':'git_worktree','branch':branch,'root':str(destination)}
    destination.mkdir(parents=True,exist_ok=True)
    return {'kind':'disposable_copy','root':str(destination),'branch':None}


def commit(root,paths,message):
    if not isinstance(message,str) or not 1<=len(message)<=300:raise ValueError('Нужно короткое сообщение коммита')
    for name in paths:Project(root).path(name,text_only=False)
    r=command(root,'add','--',*paths)
    if r['exit_code']!=0:return r
    return command(root,'-c','user.name=META Local','-c','user.email=meta@localhost','commit','-m',message)
