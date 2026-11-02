"""Small prompt_toolkit + Rich terminal front end for META Code stage 1."""
import json
import sys
from pathlib import Path
from .engine import Workspace,Agent

def main():
    try:
        from rich.console import Console
        from rich.panel import Panel
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
    except ImportError:
        print('Install CLI dependencies: python -m pip install rich prompt_toolkit')
        return 1
    console=Console()
    root=Path(sys.argv[1] if len(sys.argv)>1 else '.').resolve()
    if not root.is_dir():
        console.print('[red]Workspace directory not found[/red]');return 1
    cfg=Path(__file__).parent/'config.json'
    options=json.loads(cfg.read_text('utf-8')) if cfg.is_file() else {}
    def approve(action,detail):
        console.print(Panel(detail[:2200],title='Подтверждение: '+action,border_style='yellow'))
        return console.input('[bold]Разрешить это действие? [y/N]: [/bold]').strip().lower() in ('y','yes','да')
    workspace=Workspace(root,approve)
    def callback(event,name,detail):
        if event=='tool':console.print(f'[cyan]● {name}[/cyan]')
        else:console.print('[dim]  ⎿ '+str(detail)[:160].replace('\n',' ')+'[/dim]')
    agent=Agent(workspace,model=options.get('model','qwen2.5-coder:7b'),max_steps=options.get('max_steps',12),callback=callback)
    console.print(Panel(f'[bold]META Code · Stage 1[/bold]\nПапка: {root}\nМодель: {agent.model}\n/exit — выход; /help — справка',border_style='dark_orange'))
    history=FileHistory(str(Path.home()/'.meta_code_history'))
    session=PromptSession(history=history,multiline=False)
    while True:
        try:text=session.prompt('> ').strip()
        except (KeyboardInterrupt,EOFError):break
        if not text:continue
        if text=='/exit':break
        if text=='/help':console.print('/help · /exit · остальные команды будут в следующих этапах');continue
        try:console.print('\n'+agent.run(text)+'\n')
        except KeyboardInterrupt:console.print('[yellow]Прервано[/yellow]')
        except Exception as exc:console.print(f'[red]Ошибка: {exc}[/red]')
    return 0

if __name__=='__main__':raise SystemExit(main())
