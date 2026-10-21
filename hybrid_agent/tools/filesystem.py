"""File tools: read, write, edit, list, find, search. All sandboxed to the workspace."""
from __future__ import annotations

import fnmatch
import os
import re

from ..safety import resolve_in_workspace
from .registry import ToolContext, ToolError, ToolRegistry

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".agent"}


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


def register(reg: ToolRegistry) -> None:

    @reg.tool("read_file",
              "Read a text file from the workspace. Returns numbered lines. "
              "Use offset/limit for large files.",
              _obj({"path": {"type": "string", "description": "Path relative to the workspace"},
                    "offset": {"type": "integer", "description": "First line (1-based), default 1"},
                    "limit": {"type": "integer", "description": "Max lines, default 400"}},
                   ["path"]))
    def read_file(ctx: ToolContext, path: str, offset: int = 1, limit: int = 400):
        p = resolve_in_workspace(ctx.workspace, path)
        if not p.is_file():
            raise ToolError(f"No such file: {path}")
        lines = p.read_text(errors="replace").splitlines()
        start = max(offset, 1) - 1
        chunk = lines[start:start + limit]
        body = "\n".join(f"{i:>5}  {line}" for i, line in enumerate(chunk, start + 1))
        more = len(lines) - (start + len(chunk))
        return body + (f"\n... ({more} more lines)" if more > 0 else "")

    @reg.tool("write_file",
              "Create or overwrite a text file in the workspace. Creates parent folders.",
              _obj({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]))
    def write_file(ctx: ToolContext, path: str, content: str):
        p = resolve_in_workspace(ctx.workspace, path)
        if p.exists() and not ctx.approver("write_file", {"path": path}, "overwrite existing file"):
            raise ToolError("User declined overwriting the existing file.")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"Wrote {len(content)} chars to {path}"

    @reg.tool("edit_file",
              "Replace an exact snippet in a file. old_text must appear exactly once "
              "(unless replace_all is true). Read the file first.",
              _obj({"path": {"type": "string"}, "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "replace_all": {"type": "boolean"}},
                   ["path", "old_text", "new_text"]))
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

    @reg.tool("list_dir",
              "List files and folders in a workspace directory (non-recursive).",
              _obj({"path": {"type": "string", "description": "Default '.'"}}, []))
    def list_dir(ctx: ToolContext, path: str = "."):
        p = resolve_in_workspace(ctx.workspace, path)
        if not p.is_dir():
            raise ToolError(f"Not a directory: {path}")
        rows = []
        for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name)):
            rows.append(f"{child.name}/" if child.is_dir() else f"{child.name}  ({child.stat().st_size} B)")
        return "\n".join(rows) or "(empty)"

    @reg.tool("find_files",
              "Find files by glob pattern (e.g. '*.py', 'src/**/*.md') under the workspace.",
              _obj({"pattern": {"type": "string"}}, ["pattern"]))
    def find_files(ctx: ToolContext, pattern: str):
        root = ctx.workspace.resolve()
        hits = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                rel = os.path.relpath(os.path.join(dirpath, f), root)
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(f, pattern):
                    hits.append(rel)
            if len(hits) >= 500:
                break
        return "\n".join(sorted(hits)) or "No matches."

    @reg.tool("search_text",
              "Search file contents with a regular expression. Returns path:line: text.",
              _obj({"regex": {"type": "string"},
                    "glob": {"type": "string", "description": "Only files matching this glob"},
                    "ignore_case": {"type": "boolean"}},
                   ["regex"]))
    def search_text(ctx: ToolContext, regex: str, glob: str = "*", ignore_case: bool = False):
        try:
            rx = re.compile(regex, re.IGNORECASE if ignore_case else 0)
        except re.error as e:
            raise ToolError(f"Bad regex: {e}")
        root = ctx.workspace.resolve()
        out = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                if not fnmatch.fnmatch(f, glob):
                    continue
                full = os.path.join(dirpath, f)
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
