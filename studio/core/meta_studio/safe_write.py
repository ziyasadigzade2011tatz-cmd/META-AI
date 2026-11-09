"""Backed-up, checked file replacement with rollback on ordinary failures."""
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path


def apply_changes(changes, backup_root, digest):
    # changes: [(target_path, new_text, expected_old_hash), ...]
    entries = []
    seen = set()

    for target, content, expected in changes:
        target = Path(target)

        if target in seen:
            raise ValueError("Duplicate target: " + str(target))
        seen.add(target)

        if target.is_symlink():
            raise ValueError("Symbolic-link target refused: " + str(target))
        if not isinstance(content, str):
            raise TypeError("New content must be text")

        old = target.read_bytes() if target.exists() else None

        if digest(old) != expected:
            raise ValueError("File changed before apply: " + str(target))

        entries.append({
            "target": target,
            "content": content,
            "expected": expected,
            "old": old,
            "stage": None,
            "backup": None,
        })

    if not entries:
        return {"applied": True, "files": [], "backup": None}

    backup_root = Path(backup_root).resolve()
    backup_root.mkdir(parents=True, exist_ok=True)

    directory = backup_root / ("transaction_" + uuid.uuid4().hex)
    directory.mkdir(exist_ok=False)

    manifest = directory / "manifest.json"
    committed = []

    def record(status, error=None):
        information = {
            "status": status,
            "error": error,
            "files": [
                {
                    "target": str(e["target"].resolve()),
                    "existed": e["old"] is not None,
                    "backup": str(e["backup"]) if e["backup"] else None,
                }
                for e in entries
            ],
        }
        manifest.write_text(
            json.dumps(information, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    try:
        # Create persistent backups before replacing any file.
        for index, e in enumerate(entries):
            if e["old"] is not None:
                backup = directory / ("original_" + str(index) + ".bin")
                backup.write_bytes(e["old"])

                if backup.read_bytes() != e["old"]:
                    raise OSError("Backup verification failed")

                e["backup"] = backup

        record("prepared")

        # Stage all replacement files before committing any.
        for e in entries:
            e["target"].parent.mkdir(parents=True, exist_ok=True)

            fd, name = tempfile.mkstemp(
                prefix=".meta-stage-",
                dir=str(e["target"].parent)
            )
            e["stage"] = Path(name)

            with os.fdopen(fd, "wb") as stream:
                stream.write(e["content"].encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())

        # Recheck the original state immediately before each replacement.
        for e in entries:
            target = e["target"]

            if target.is_symlink():
                raise ValueError("Target became symbolic link")

            current = target.read_bytes() if target.exists() else None
            if digest(current) != e["expected"]:
                raise ValueError("File changed during apply: " + str(target))

            os.replace(e["stage"], target)
            committed.append(e)
            e["stage"] = None

        record("completed")

        return {
            "applied": True,
            "files": [str(e["target"]) for e in entries],
            "backup": str(directory),
        }

    except Exception as error:
        rollback_errors = []

        for e in reversed(committed):
            try:
                target = e["target"]

                if e["old"] is None:
                    target.unlink(missing_ok=True)
                else:
                    fd, name = tempfile.mkstemp(
                        prefix=".meta-restore-",
                        dir=str(target.parent)
                    )
                    os.close(fd)
                    restore = Path(name)

                    try:
                        shutil.copy2(e["backup"], restore)
                        os.replace(restore, target)
                    finally:
                        restore.unlink(missing_ok=True)

                    if target.read_bytes() != e["old"]:
                        raise OSError("Restored content mismatch")

            except Exception as restore_error:
                rollback_errors.append(str(restore_error))

        try:
            record(
                "rollback_failed" if rollback_errors else "rolled_back",
                str(error)
            )
        except Exception:
            pass

        if rollback_errors:
            raise RuntimeError(
                "Rollback incomplete. Preserve backup: "
                + str(directory)
                + " | "
                + "; ".join(rollback_errors)
            ) from error

        raise

    finally:
        for e in entries:
            if e["stage"] is not None:
                e["stage"].unlink(missing_ok=True)
