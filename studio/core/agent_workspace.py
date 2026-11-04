import os
from pathlib import Path
import re

PROJECTS = Path(os.environ.get('META_PROJECTS_DIR',str(Path.home()/'META Projects')))
EXTENSIONS = {
    ".py", ".md", ".txt", ".json",
    ".html", ".css", ".js", ".ts",
    ".toml", ".yaml", ".yml"
}
MAX_FILE_BYTES = 8000


def safe_path(relative_path, root=PROJECTS):
    root = Path(root).resolve()
    target = (root / relative_path).resolve()

    if not target.is_relative_to(root):
        raise PermissionError("Access outside Projects is denied")

    return target


def list_project_files(root=PROJECTS):
    root = Path(root)
    if not root.is_dir():
        return []

    items = []

    for path in root.rglob("*"):
        if len(items) >= 35:
            break
        if not path.is_file():
            continue
        if path.suffix.lower() not in EXTENSIONS:
            continue

        try:
            verified = safe_path(path.relative_to(root), root)
            if verified != path.resolve():
                continue
            items.append(str(path.relative_to(root)))
        except (OSError, ValueError, PermissionError):
            continue

    return items


def read_project_file(relative_path, root=PROJECTS):
    path = safe_path(relative_path, root)

    if path.suffix.lower() not in EXTENSIONS:
        raise PermissionError("File extension not allowed")

    if not path.is_file():
        raise FileNotFoundError(relative_path)

    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("File too large for this stage")

    return path.read_text(encoding="utf-8")


def project_snapshot(task, root=PROJECTS):
    files = list_project_files(root)
    output = [
        "PROJECT FILES (read-only):",
        "\n".join(files) if files else "No eligible files found"
    ]

    # Explicit @file mentions only.
    mentions = re.findall(
        r"@([A-Za-z0-9_./\\-]+\.(?:py|md|txt|json|html|css|js|ts|toml|yaml|yml))\b",
        task,
        flags=re.IGNORECASE
    )

    for relative in dict.fromkeys(mentions[:2]):
        try:
            content = read_project_file(relative, root)
            output.append(
                "\nFILE: " + relative + "\n" + content
            )
        except (OSError, ValueError, PermissionError) as error:
            output.append(
                "\nFILE ERROR: " + relative
                + " (" + type(error).__name__ + ")"
            )

    return "\n".join(output)[:7000]
