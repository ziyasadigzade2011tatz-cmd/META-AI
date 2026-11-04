from pathlib import Path

import os
WORKSPACE = Path(os.environ.get('META_PROJECTS_DIR',str(Path.home()/'META Projects'))).absolute()
WORKSPACE.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".py", ".json",
    ".html", ".css", ".js", ".csv",
    ".yaml", ".yml"
}


def safe_path(relative_path):
    if not isinstance(relative_path, str):
        raise ValueError("Invalid path")

    from meta40.workspace import Workspace, relative, reparse
    root = Workspace(WORKSPACE).root
    relative_path = relative_path.replace('\\','/')
    if relative_path == '.':
        return root
    parts = relative(relative_path)
    path = root.joinpath(*parts)
    for item in [path,*path.parents]:
        if item.is_symlink() or (item.exists() and reparse(item)):
            raise ValueError('Links and junctions are forbidden')
        if item == root: break
    path = path.resolve()

    if not path.is_relative_to(root):
        raise ValueError("Access outside META Projects denied")

    return path


def list_files(folder="."):
    path = safe_path(folder)

    if not path.is_dir():
        raise ValueError("Folder not found")

    return [
        {
            "name": item.name,
            "type": "folder" if item.is_dir() else "file"
        }
        for item in sorted(path.iterdir())
        if item.resolve().is_relative_to(WORKSPACE)
    ][:100]


def read_file(file_path):
    path = safe_path(file_path)

    if not path.is_file():
        raise ValueError("File not found")

    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file type")

    if path.stat().st_size > 100000:
        raise ValueError("File is too large")

    return path.read_text(encoding="utf-8")


def create_file(file_path, content):
    """Prepare a proposal; no tool is allowed to write the live project directly."""
    target = safe_path(file_path)
    if target.exists():
        raise ValueError("File already exists; use a reviewed edit proposal")
    from meta40.workspace import validate_content
    validate_content(file_path.replace("\\", "/"),content)
    from agent_pending import stage
    proposal = stage(file_path,content)
    return {**proposal, "created":False, "applied":False,
            "message":"Заявка подготовлена. Файл будет создан после подтверждения."}
