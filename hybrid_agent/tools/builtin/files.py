"""[TOOLS / files] Read, write, edit, search and manage files. Sandboxed to the workspace.

Tools: read_file, write_file, append_file, edit_file, list_dir, tree, find_files,
       search_text, file_info, make_dir, copy_path, move_path, delete_path, diff_files
"""
from __future__ import annotations

import datetime as dt
import difflib
import fnmatch
import os
import shutil

from ...core.safety import resolve_in_workspace
from ..registry import S, ToolContext, ToolError, ToolRegistry

CATEGORY = "files"
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".agent", ".mypy_cache"}


def is_binary(path: str | os.PathLike) -> bool:
    """Heuristic: a NUL byte in the first 8 KB means binary."""
    try:
        with open(path, "rb") as f:
            return b"\0" in f.read(8192)
    except OSError:
        return True


def walk_files(root):
    """Yield every file under root, skipping tool/VCS folders."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for f in sorted(filenames):
            yield os.path.join(dirpath, f)


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def register(reg: ToolRegistry) -> None:
    t = lambda *a, **k: reg.tool(*a, category=CATEGORY, **k)  # noqa: E731

    @t("read_file", "Read a text file from the workspace. Returns numbered lines. "
       "Use offset/limit for large files.",
       S(path="string|Path relative to the workspace",
         offset="integer?|First line (1-based), default 1",
         limit="integer?|Max lines, default 400"))
    def read_file(ctx: ToolContext, path: str, offset: int = 1, limit: int = 400):
        p = resolve_in_workspace(ctx.workspace, path)
        if not p.is_file():
            raise ToolError(f"No such file: {path}")
        if is_binary(p):
            raise ToolError(f"{path} is a binary file ({_human(p.stat().st_size)}); use file_info or hash_file.")
        lines = p.read_text(errors="replace").splitlines()
        start = max(offset, 1) - 1
        chunk = lines[start:start + limit]
        body = "\n".join(f"{i:>5}  {line}" for i, line in enumerate(chunk, start + 1))
        more = len(lines) - (start + len(chunk))
        return (body or "(empty file)") + (f"\n... ({more} more lines)" if more > 0 else "")

    @t("write_file", "Create or overwrite a text file in the workspace. Creates parent folders.",
       S(path="string", content="string"), risk="write")
    def write_file(ctx: ToolContext, path: str, content: str):
        p = resolve_in_workspace(ctx.workspace, path)
        if p.exists() and not ctx.approver("write_file", {"path": path}, "overwrite existing file"):
            raise ToolError("User declined overwriting the existing file.")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"Wrote {len(content)} chars to {path}"

    @t("append_file", "Append text to the end of a file (creates it if missing). "
       "Good for building large files in pieces or keeping a log.",
       S(path="string", content="string"), risk="write")
    def append_file(ctx: ToolContext, path: str, content: str):
        p = resolve_in_workspace(ctx.workspace, path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(content)
        return f"Appended {len(content)} chars to {path}"

    @t("edit_file", "Replace an exact snippet in a file. old_text must appear exactly once "
       "(unless replace_all is true). Read the file first.",
       S(path="string", old_text="string", new_text="string", replace_all="boolean?"), risk="write")
    def edit_file(ctx: ToolContext, path: str, old_text: str, new_text: str, replace_all: bool = False):
        p = resolve_in_workspace(ctx.workspace, path)
        if not p.is_file():
            raise ToolError(f"No such file: {path}")
        text = p.read_text()
        n = text.count(old_text)
        if n == 0:
            raise ToolError("old_text not found. Re-read the file and copy the text exactly.")
        if n > 1 and not replace_all:
            raise ToolError(f"old_text appears {n} times; add more context or set replace_all.")
        p.write_text(text.replace(old_text, new_text) if replace_all else text.replace(old_text, new_text, 1))
        return f"Edited {path} ({n if replace_all else 1} replacement(s))"

    @t("list_dir", "List files and folders in one workspace directory (non-recursive).",
       S(path="string?|Default '.'"))
    def list_dir(ctx: ToolContext, path: str = "."):
        p = resolve_in_workspace(ctx.workspace, path)
        if not p.is_dir():
            raise ToolError(f"Not a directory: {path}")
        rows = []
        for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name)):
            rows.append(f"{child.name}/" if child.is_dir() else f"{child.name}  ({_human(child.stat().st_size)})")
        return "\n".join(rows) or "(empty)"

    @t("tree", "Show the folder structure as an indented tree.",
       S(path="string?|Default '.'", max_depth="integer?|Default 3"))
    def tree(ctx: ToolContext, path: str = ".", max_depth: int = 3):
        root = resolve_in_workspace(ctx.workspace, path)
        if not root.is_dir():
            raise ToolError(f"Not a directory: {path}")
        lines = [f"{root.name or '.'}/"]

        def walk(d, depth, prefix):
            if depth > max_depth or len(lines) > 400:
                return
            kids = sorted((c for c in d.iterdir() if c.name not in SKIP_DIRS),
                          key=lambda c: (not c.is_dir(), c.name))
            for i, c in enumerate(kids):
                last = i == len(kids) - 1
                lines.append(f"{prefix}{'└── ' if last else '├── '}{c.name}{'/' if c.is_dir() else ''}")
                if c.is_dir():
                    walk(c, depth + 1, prefix + ("    " if last else "│   "))
        walk(root, 1, "")
        return "\n".join(lines)

    @t("find_files", "Find files by glob pattern (e.g. '*.py', 'src/**/*.md') under the workspace.",
       S(pattern="string"))
    def find_files(ctx: ToolContext, pattern: str):
        root = ctx.workspace.resolve()
        hits = []
        for full in walk_files(root):
            rel = os.path.relpath(full, root)
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(os.path.basename(full), pattern):
                hits.append(rel)
                if len(hits) >= 500:
                    break
        return "\n".join(hits) or "No matches."

    @t("search_text", "Search text-file contents with a regular expression. Returns path:line: text. "
       "Binary files are skipped.",
       S(regex="string", glob="string?|Only files whose name matches this glob",
         ignore_case="boolean?"))
    def search_text(ctx: ToolContext, regex: str, glob: str = "*", ignore_case: bool = False):
        import re
        try:
            rx = re.compile(regex, re.IGNORECASE if ignore_case else 0)
        except re.error as e:
            raise ToolError(f"Bad regex: {e}")
        root = ctx.workspace.resolve()
        out = []
        for full in walk_files(root):
            if not fnmatch.fnmatch(os.path.basename(full), glob) or is_binary(full):
                continue
            try:
                with open(full, errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if rx.search(line):
                            out.append(f"{os.path.relpath(full, root)}:{i}: {line.rstrip()[:300]}")
                            if len(out) >= 200:
                                return "\n".join(out) + "\n...(stopped at 200 matches)"
            except OSError:
                continue
        return "\n".join(out) or "No matches."

    @t("file_info", "Size, type, line count and timestamps of a file or folder.", S(path="string"))
    def file_info(ctx: ToolContext, path: str):
        p = resolve_in_workspace(ctx.workspace, path)
        if not p.exists():
            raise ToolError(f"No such path: {path}")
        st = p.stat()
        info = {"path": path, "type": "directory" if p.is_dir() else "file",
                "size": _human(st.st_size),
                "modified": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")}
        if p.is_file():
            info["binary"] = is_binary(p)
            if not info["binary"]:
                with p.open(errors="replace") as f:
                    info["lines"] = sum(1 for _ in f)
        else:
            info["entries"] = sum(1 for _ in p.iterdir())
        return info

    @t("make_dir", "Create a folder (and any missing parents).", S(path="string"), risk="write")
    def make_dir(ctx: ToolContext, path: str):
        resolve_in_workspace(ctx.workspace, path).mkdir(parents=True, exist_ok=True)
        return f"Created {path}/"

    @t("copy_path", "Copy a file or folder inside the workspace.",
       S(source="string", destination="string"), risk="write")
    def copy_path(ctx: ToolContext, source: str, destination: str):
        src = resolve_in_workspace(ctx.workspace, source)
        dst = resolve_in_workspace(ctx.workspace, destination)
        if not src.exists():
            raise ToolError(f"No such path: {source}")
        if dst.exists():
            raise ToolError(f"{destination} already exists.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, dst)
        return f"Copied {source} -> {destination}"

    @t("move_path", "Move or rename a file or folder inside the workspace.",
       S(source="string", destination="string"), risk="write", requires_approval=True)
    def move_path(ctx: ToolContext, source: str, destination: str):
        src = resolve_in_workspace(ctx.workspace, source)
        dst = resolve_in_workspace(ctx.workspace, destination)
        if not src.exists():
            raise ToolError(f"No such path: {source}")
        if dst.exists():
            raise ToolError(f"{destination} already exists.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(src, dst)
        return f"Moved {source} -> {destination}"

    @t("delete_path", "Delete a file, or a folder and everything in it.",
       S(path="string"), risk="write", requires_approval=True)
    def delete_path(ctx: ToolContext, path: str):
        p = resolve_in_workspace(ctx.workspace, path)
        if p == ctx.workspace.resolve():
            raise ToolError("Refusing to delete the whole workspace.")
        if not p.exists():
            raise ToolError(f"No such path: {path}")
        shutil.rmtree(p) if p.is_dir() else p.unlink()
        return f"Deleted {path}"

    @t("diff_files", "Show a unified diff between two text files.",
       S(path_a="string", path_b="string", context="integer?|Context lines, default 3"))
    def diff_files(ctx: ToolContext, path_a: str, path_b: str, context: int = 3):
        a = resolve_in_workspace(ctx.workspace, path_a)
        b = resolve_in_workspace(ctx.workspace, path_b)
        for p, n in ((a, path_a), (b, path_b)):
            if not p.is_file():
                raise ToolError(f"No such file: {n}")
        d = difflib.unified_diff(a.read_text(errors="replace").splitlines(),
                                 b.read_text(errors="replace").splitlines(),
                                 path_a, path_b, lineterm="", n=context)
        return "\n".join(d) or "Files are identical."
