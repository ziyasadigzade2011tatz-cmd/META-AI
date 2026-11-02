import ast
import hashlib
import json
import os
import re
from pathlib import Path, PureWindowsPath

EXTENSIONS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.json',
              '.md', '.txt', '.toml', '.yaml', '.yml', '.csv'}
SKIP = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.meta40', 'dist', 'build'}
MAX_FILE = 20000
MAX_TOTAL = 100000


def digest(value):
    return hashlib.sha256(value).hexdigest() if value is not None else None


def relative(name):
    if not isinstance(name, str) or not name or len(name) > 220:
        raise ValueError('Invalid relative path')
    win = PureWindowsPath(name)
    parts = name.split('/')
    if win.drive or win.root or '\\' in name or any(p in ('', '.', '..') for p in parts):
        raise ValueError('Only relative forward-slash paths are allowed')
    for part in parts:
        if (part.startswith('.') or part in SKIP or part.endswith((' ', '.'))
                or re.search(r'[<>:"|?*\x00-\x1f]', part)
                or part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                    *('COM'+str(i) for i in range(1, 10)), *('LPT'+str(i) for i in range(1, 10))}
                or any(s in part.lower() for s in ('secret', 'credential', 'password'))):
            raise ValueError('Protected or invalid path: '+name)
    return parts


def reparse(path):
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


class Workspace:
    def __init__(self, root):
        self.root = Path(root).absolute()
        if not self.root.is_dir():
            raise ValueError('Папка проекта не найдена: '+str(self.root))
        for p in [self.root, *self.root.parents]:
            if reparse(p):
                raise ValueError('Linked project roots are forbidden')
        self.root = self.root.resolve()

    def path(self, name):
        parts = relative(name)
        target = self.root.joinpath(*parts)
        for p in [target, *target.parents]:
            if p.exists() and reparse(p):
                raise ValueError('Links and junctions are forbidden')
            if p == self.root:
                break
        if not target.resolve().is_relative_to(self.root):
            raise ValueError('Outside project')
        if target.suffix.lower() not in EXTENSIONS:
            raise ValueError('Unsupported file extension')
        return target

    def inventory(self):
        result = {}
        total = 0
        visited = 0
        for folder, dirs, files in os.walk(self.root, followlinks=False):
            visited += 1
            if visited > 2000:
                raise ValueError('Project has too many directories')
            dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith('.')
                             and not reparse(Path(folder)/d))
            for f in sorted(files):
                name = (Path(folder)/f).relative_to(self.root).as_posix()
                try:
                    p = self.path(name)
                except ValueError:
                    continue
                if not p.is_file() or p.stat().st_size > MAX_FILE:
                    continue
                raw = p.read_bytes()
                try:
                    raw.decode('utf-8')
                except UnicodeError:
                    continue
                total += len(raw)
                if len(result) >= 1000 or total > 8_000_000:
                    raise ValueError('Project exceeds snapshot budget (1000 files / 8 MB)')
                result[name] = raw
        return result


def validate_content(name, content):
    relative(name)
    if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_FILE:
        raise ValueError('File content exceeds 20 KB')
    if name.lower().endswith('.py'):
        ast.parse(content, filename=name)
    if name.lower().endswith('.json'):
        json.loads(content)


def project_root(projects, project, create=False):
    base = Workspace(projects)
    if project == '.':
        return base.root
    parts = relative(project)
    target = base.root.joinpath(*parts)
    if not target.resolve().is_relative_to(base.root):
        raise ValueError('Outside Projects')
    current = base.root
    for part in parts:
        current = current/part
        if current.is_symlink() or (current.exists() and reparse(current)):
            raise ValueError('Links and junctions are forbidden')
        if current.exists():
            if not current.is_dir():
                raise ValueError('Имя проекта занято файлом: '+str(current))
        elif create:
            current.mkdir(exist_ok=True)
        else:
            raise ValueError('Папка проекта не найдена: '+str(target)+
                             '. Включи «Создать папку проекта, если её нет».')
        Workspace(current)
    return Workspace(target).root
