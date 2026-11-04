import os
from pathlib import Path
from datetime import datetime
import difflib
import sys

from agent_workspace import safe_path, EXTENSIONS

ROOT = Path(os.environ.get('META_PROJECTS_DIR',str(Path.home()/'META Projects')))
MAX_CONTENT = 50000


def prepare_change(relative_path, new_content):
    target = safe_path(relative_path)

    if target.suffix.lower() not in EXTENSIONS:
        raise PermissionError("Этот тип файла запрещён")

    if len(new_content.encode("utf-8")) > MAX_CONTENT:
        raise ValueError("Слишком большой файл")

    if target.exists() and not target.is_file():
        raise PermissionError("Путь не является обычным файлом")

    old_content = (
        target.read_text(encoding="utf-8")
        if target.exists()
        else ""
    )

    diff = "".join(difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile="BEFORE/" + str(relative_path),
        tofile="AFTER/" + str(relative_path),
    ))

    return target, old_content, diff


def apply_change(relative_path, new_content):
    target, old_content, diff = prepare_change(
        relative_path, new_content
    )

    print("\n=== META FILE CHANGE PREVIEW ===\n")
    print(diff if diff else "Изменений нет")

    if not diff:
        return "NO CHANGES"

    answer = input(
        "\nПрименить изменение? Напиши YES: "
    ).strip()

    if answer != "YES":
        return "CANCELLED"

    # Recheck after confirmation.
    checked = safe_path(relative_path)
    if checked != target:
        raise PermissionError("Путь изменился")

    current = (
        checked.read_text(encoding="utf-8")
        if checked.exists()
        else ""
    )
    if current != old_content:
        raise RuntimeError(
            "Файл изменился после просмотра. Операция отменена."
        )

    if checked.exists():
        backup = checked.with_name(
            checked.name + ".bak_"
            + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        )
        backup.write_bytes(checked.read_bytes())

    checked.parent.mkdir(parents=True, exist_ok=True)
    checked.write_text(new_content, encoding="utf-8")

    return "SAVED: " + str(checked)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: agent_write.py PATH CONTENT_FILE")
        raise SystemExit(2)

    content = Path(sys.argv[2]).read_text(encoding="utf-8")
    print(apply_change(sys.argv[1], content))
