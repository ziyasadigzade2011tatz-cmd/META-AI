"""META 3.8: bounded, review-first local coding agent.

No execution of generated code. No write outside pending changes. Never auto-approve.
Works with existing Agent Engine 3.7's proposal format.
"""
from __future__ import annotations

import ast
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import Request, urlopen

MAX_FILES = 12
MAX_TOTAL_BYTES = 100_000
MAX_INPUT_CHARS = 100_000
MAX_CONTEXT_BYTES = 48_000
REPAIR_ATTEMPTS = 2
MODEL = os.environ.get('META_CODER_MODEL', 'qwen2.5-coder:14b')
OLLAMA = 'http://127.0.0.1:11434/api/generate'
FLAG = 'META_ENGINE_38'


@dataclass
class Finding:
    path: str
    level: str
    message: str


@dataclass
class Review:
    files: list[dict] = field(default_factory=list)
    issues: list[Finding] = field(default_factory=list)
    existing_context: dict[str, str] = field(default_factory=dict)

    @property
    def blocking(self) -> bool:
        return any(i.level == 'error' for i in self.issues)


def _workspace():
    from agent_tools import WORKSPACE
    return Path(WORKSPACE).resolve()


def _target(relative):
    from agent_tools import safe_path
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('Invalid relative path')
    if Path(relative).is_absolute() or any(x in ('', '.', '..') for x in relative.split('/')):
        raise ValueError('Invalid relative path segments')
    path = safe_path(relative)
    root = _workspace()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('Outside workspace')
    # Avoid symlinks in ALL components (resolve() alone would silently follow them).
    cur = root
    for part in Path(relative).parts:
        cur = cur / part
        if cur.is_symlink():
            raise ValueError('Symlinks not supported')
    return path


def project_inventory(limit=80):
    root = _workspace()
    ignored = {'.git', '.venv', 'venv', '__pycache__', 'node_modules', 'dist', 'build'}
    out = []
    for base, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in ignored and not (Path(base) / d).is_symlink())
        for name in sorted(names):
            p = Path(base) / name
            if p.is_symlink() or p.suffix.lower() not in {'.py', '.json', '.md', '.js', '.html', '.css', '.txt'}:
                continue
            try:
                st = p.stat()
                if st.st_size > 100_000:
                    continue
                out.append(p.relative_to(root).as_posix())
                if len(out) >= limit:
                    return out
            except OSError:
                continue
    return out


def audit(files: list[dict]) -> Review:
    from agent_tools import ALLOWED_EXTENSIONS
    result = Review(files=files)
    if not isinstance(files, list) or len(files) < 1 or len(files) > MAX_FILES:
        result.issues.append(Finding('*', 'error', 'Expected 1–12 named files'))
        return result
    seen = set()
    total = 0
    declared = set()
    for obj in files:
        if not isinstance(obj, dict) or not isinstance(obj.get('path'), str) or not isinstance(obj.get('content'), str):
            result.issues.append(Finding('*', 'error', 'Invalid file object'))
            continue
        name, content = obj['path'], obj['content']
        total += len(content.encode('utf-8'))
        if name.casefold() in seen:
            result.issues.append(Finding(name, 'error', 'Duplicate path'))
        seen.add(name.casefold())
        try:
            target = _target(name)
            if target.suffix.lower() not in ALLOWED_EXTENSIONS:
                raise ValueError('Unsupported extension')
            if not target.parent.is_dir():
                raise ValueError('Parent directory does not exist')
            if target.exists() and (not target.is_file() or target.stat().st_size > 100_000):
                raise ValueError('Existing file invalid or too large')
            declared.add(name)
        except (ValueError, OSError) as exc:
            result.issues.append(Finding(name, 'error', str(exc)))
            continue
        if not content.strip():
            result.issues.append(Finding(name, 'error', 'Empty content'))
        if target.suffix.lower() == '.py':
            try:
                tree = ast.parse(content, filename=name)
            except SyntaxError as exc:
                result.issues.append(Finding(name, 'error', f'Python syntax line {exc.lineno}: {exc.msg}'))
            else:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        fn = node.func
                        # Warnings only: static AST cannot prove malicious or safe behavior.
                        if isinstance(fn, ast.Name) and fn.id in ('eval', 'exec'):
                            result.issues.append(Finding(name, 'warning', f'Dynamic code execution ({fn.id}) at line {node.lineno}'))
                        if isinstance(fn, ast.Attribute) and fn.attr in ('system', 'Popen', 'run', 'rmtree'):
                            result.issues.append(Finding(name, 'warning', f'Potential subprocess/deletion call at line {node.lineno}'))
        elif target.suffix.lower() == '.json':
            try: json.loads(content)
            except json.JSONDecodeError as exc:
                result.issues.append(Finding(name, 'error', f'JSON line {exc.lineno}: {exc.msg}'))
    if total > MAX_TOTAL_BYTES:
        result.issues.append(Finding('*', 'error', 'Total proposed content exceeds 100 KB'))
    return result


def _read_context(files):
    """Read small existing target files only. Never include unrelated secrets in model prompt."""
    context = {}
    budget = MAX_CONTEXT_BYTES
    for obj in files:
        try:
            target = _target(obj['path'])
            if not target.is_file() or target.stat().st_size > min(12_000, budget):
                continue
            raw = target.read_bytes()
            content = raw.decode('utf-8')
            context[obj['path']] = content
            budget -= len(raw)
            if budget <= 0: break
        except (KeyError, OSError, UnicodeError, ValueError):
            continue
    return context


def _ollama_repair(task, files, issues, context):
    details = '\n'.join(f'- {i.path}: {i.message}' for i in issues if i.level == 'error')
    original = '\n\n'.join(f"Файл: {f['path']}\n```\n{f['content']}\n```" for f in files)
    previous = '\n\n'.join(f"Existing {name}:\n```\n{content}\n```" for name, content in context.items())
    prompt = ("You are a local coding repair assistant. Repair ONLY errors listed below. "
              "Return complete corrected files, each under a heading 'Файл: relative/path.py' "
              "followed by a fenced code block. Preserve existing behavior. "
              "Do not include shell commands, commentary, or files outside the requested set.\n\n"
              f"Task:\n{task[:6000]}\n\nErrors:\n{details[:4500]}\n\n"
              f"Existing versions:\n{previous[:MAX_CONTEXT_BYTES]}\n\nProposed files:\n{original[:MAX_INPUT_CHARS]}")
    payload = json.dumps({'model': MODEL, 'prompt': prompt, 'stream': False,
                          'options': {'temperature': .15, 'num_predict': 6000}}, ensure_ascii=False).encode('utf-8')
    req = Request(OLLAMA, data=payload, headers={'Content-Type':'application/json'}, method='POST')
    with urlopen(req, timeout=240) as resp:
        answer = json.loads(resp.read(2_000_000).decode('utf-8'))
    return answer.get('response', '')


def extract_unchecked(text):
    """Extract named fenced blocks WITHOUT parsing syntax, allowing a repair pass."""
    if '### Результат Coder' in text:
        text = text.split('### Результат Coder', 1)[1].split('\n### ', 1)[0]
    fence = re.compile(r'```([^\n`]*)\n([\s\S]*?)```')
    line = re.compile(r'(?:^|\n)\s*(?:#{1,5}\s*)?(?:Файл|File|Path)\s*:\s*`?([\w.\-/ ]+\.[a-zA-Z0-9]+)`?\s*$', re.I)
    file_name = re.compile(r'^[\w.\-/ ]+\.(?:py|js|json|html|css|md|txt|yaml|yml|csv)$', re.I)
    found = []
    for m in fence.finditer(text):
        named = None
        for word in m.group(1).split():
            if word.startswith(('filename=', 'file=')):
                named = word.split('=', 1)[1].strip('`"\'')
            elif file_name.fullmatch(word):
                named = word
        if not named:
            prefix = text[max(0, m.start()-200):m.start()]
            previous = line.search(prefix)
            if previous: named = previous.group(1).strip()
        if named:
            found.append({'path':named, 'content':m.group(2)})
    return found


def process(task, team_response, previous_stage):
    """Optional static audit and repair before staging. Never auto-write files."""
    from agent_project37 import stage_project
    if not isinstance(team_response, str) or len(team_response) > 250_000:
        return previous_stage(task, team_response)
    # 3.8 engages only for explicit coding tasks. Existing workflows remain intact.
    trigger = any(t in task.lower() for t in ('команда агентов:', 'meta code:', 'мета код:'))
    if not trigger:
        return previous_stage(task, team_response)
    try:
        files = extract_unchecked(team_response)
    except Exception as exc:
        return team_response + '\n\n**META 3.8:** не удалось разобрать файлы: ' + str(exc)
    if len(files) < 2:
        return previous_stage(task, team_response)
    review = audit(files)
    repairs = 0
    repair_note = ''
    context = _read_context(files)
    original_paths = {f['path'] for f in files}
    while review.blocking and repairs < REPAIR_ATTEMPTS:
        repairs += 1
        try:
            rewritten = _ollama_repair(task, files, review.issues, context)
            replacement = extract_unchecked(rewritten)
            if {f['path'] for f in replacement} != original_paths:
                raise ValueError('Coder changed the requested file list')
            files = replacement
            review = audit(files)
            repair_note = f'Исправлений через Ollama: {repairs}. '
        except Exception as exc:
            repair_note = f'Автоисправление остановлено: {type(exc).__name__}: {exc}. '
            break
    errors = [x for x in review.issues if x.level == 'error']
    warnings = [x for x in review.issues if x.level == 'warning']
    if errors:
        return (team_response + '\n\n### META 3.8 · проверка не пройдена\n'
                + repair_note + '\n'.join(f'- `{x.path}`: {x.message}' for x in errors[:15])
                + '\n**Заявка не создана**, файлы не изменены.')
    try:
        proposal = stage_project(files)
    except Exception as exc:
        return team_response + '\n\n**META 3.8: заявка не создана:** ' + str(exc)
    report = ('\n\n### META 3.8 · проверено перед подтверждением\n'
              + repair_note
              + f'Проверено файлов: {len(files)}. Ошибок: 0. Предупреждений: {len(warnings)}.\n'
              + '**ID заявки:** ' + proposal['id'] + '\n'
              + '**Статус:** ожидает подтверждения.\n'
              + '**Файловая заявка:** ' + ', '.join(proposal['files']) + '\n'
              + 'Проверь изменения в карточке; код не запускался и файлы не применены.')
    if warnings:
        report += '\n**Предупреждения:**\n' + '\n'.join(f'- {i.path}: {i.message}' for i in warnings[:8])
    if repairs:
        report += '\n\n### Исправленные файлы\n' + '\n\n'.join(
            f"Файл: {f['path']}\n```{Path(f['path']).suffix.lstrip('.')}\n{f['content']}\n```" for f in files)
    return team_response + report
