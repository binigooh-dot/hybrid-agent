"""[SECURITY / backup] Automatic backups before every destructive file change - and an undo.

Before a file tool overwrites, edits, moves or deletes something, the original
is copied to <workspace>/.agent/backups/<id>/ and recorded in index.json.
Delete never destroys: the item is moved there (a trash can). restore() puts
it back. The oldest backups are pruned when the total passes the size cap.

The backups folder is off-limits to the agent's own file tools and read-only
inside the command sandbox, so a confused or hijacked agent can't erase its undo history.

Analogy: "track changes" for the whole workspace.
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

from ..core.errors import ToolError

MAX_BACKUP_BYTES = 1_000_000_000      # total size kept; oldest pruned first
MAX_SINGLE_BYTES = 500_000_000        # larger items can't be backed up (the tool then refuses or warns)


def _root(workspace: Path) -> Path:
    return workspace.resolve() / ".agent" / "backups"


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _index(workspace: Path) -> list[dict]:
    f = _root(workspace) / "index.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_index(workspace: Path, entries: list[dict]) -> None:
    f = _root(workspace) / "index.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=1), encoding="utf-8")
    tmp.replace(f)


def snapshot(workspace: Path, target: Path, action: str, move: bool = False) -> dict | None:
    """Back up `target` (file or folder) before `action`. move=True for deletes (trash).
    Returns the index entry, or None if there was nothing to back up."""
    if not target.exists():
        return None
    size = _size(target)
    if size > MAX_SINGLE_BYTES:
        raise ToolError(f"{target.name} is {size / 1e6:.0f} MB - too large to back up safely, so this "
                        f"{action} was refused. Ask the user to do it themselves.")
    ws = workspace.resolve()
    rel = target.resolve().relative_to(ws)
    bid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    dest = _root(workspace) / bid / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(str(target), str(dest))
    elif target.is_dir():
        shutil.copytree(target, dest, symlinks=True)
    else:
        shutil.copy2(target, dest)
    entry = {"id": bid, "path": rel.as_posix(), "action": action, "bytes": size, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    entries = _index(workspace) + [entry]
    total = sum(e["bytes"] for e in entries)
    while total > MAX_BACKUP_BYTES and len(entries) > 1:    # prune oldest
        old = entries.pop(0)
        shutil.rmtree(_root(workspace) / old["id"], ignore_errors=True)
        total -= old["bytes"]
    _save_index(workspace, entries)
    return entry


def list_backups(workspace: Path, path_filter: str = "") -> list[dict]:
    return [e for e in reversed(_index(workspace)) if path_filter in e["path"]]


def restore(workspace: Path, backup_id: str) -> str:
    """Put a backed-up item back. Whatever is at that path now is itself backed up first."""
    entry = next((e for e in _index(workspace) if e["id"] == backup_id), None)
    if not entry:
        raise ToolError(f"No backup with id {backup_id!r}. Use list_backups to see them.")
    src = _root(workspace) / entry["id"] / entry["path"]
    if not src.exists():
        raise ToolError("That backup's files are missing (pruned or removed).")
    dest = workspace.resolve() / entry["path"]
    if dest.exists():
        snapshot(workspace, dest, "replaced by restore", move=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dest, symlinks=True)
    else:
        shutil.copy2(src, dest)
    return entry["path"]
