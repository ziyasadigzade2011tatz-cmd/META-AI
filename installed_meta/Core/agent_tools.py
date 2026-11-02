from pathlib import Path

WORKSPACE = Path(r"D:\META\Projects").resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".py", ".json",
    ".html", ".css", ".js", ".csv",
    ".yaml", ".yml"
}


def safe_path(relative_path):
    if not isinstance(relative_path, str):
        raise ValueError("Invalid path")

    path = (WORKSPACE / relative_path).resolve()

    if not path.is_relative_to(WORKSPACE):
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
    path = safe_path(file_path)

    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file type")

    if len(content) > 20000:
        raise ValueError("Content too large")

    if not path.parent.is_dir():
        raise ValueError("Parent folder does not exist")

    with path.open("x", encoding="utf-8") as file:
        file.write(content)

    return {
        "created": True,
        "path": str(path)
    }
