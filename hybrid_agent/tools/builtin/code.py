"""[TOOLS / code] Understand and check code; work with git.

Tools: code_outline, check_syntax, run_tests, git_status, git_diff, git_log, git_commit

`code_outline` and `check_syntax` are pure Python (no execution). The git and
test tools call the `git` / `python` programs in the workspace.
"""
from __future__ import annotations

import ast
import json
import re
import sys

from ...core.safety import resolve_in_workspace
from ..registry import S, ToolContext, ToolError, ToolRegistry
from .shell import run_process

CATEGORY = "code"


def python_outline(source: str) -> list[str]:
    """Classes, functions and methods with line numbers and signatures."""
    tree = ast.parse(source)
    out: list[str] = []

    def sig(fn) -> str:
        try:
            return f"{fn.name}({ast.unparse(fn.args)})"
        except Exception:
            return fn.name + "(...)"

    def visit(nodes, indent):
        for n in nodes:
            if isinstance(n, ast.ClassDef):
                out.append(f"{'  ' * indent}L{n.lineno} class {n.name}")
                visit(n.body, indent + 1)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                prefix = "async def" if isinstance(n, ast.AsyncFunctionDef) else "def"
                doc = ast.get_docstring(n)
                first = f"  # {doc.splitlines()[0][:80]}" if doc else ""
                out.append(f"{'  ' * indent}L{n.lineno} {prefix} {sig(n)}{first}")
    visit(tree.body, 0)
    return out


_GENERIC_DEF = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class|def|func|fn|interface|struct|type|public|private|protected)\b.*",
)


def register(reg: ToolRegistry) -> None:
    t = lambda *a, **k: reg.tool(*a, category=CATEGORY, **k)  # noqa: E731

    @t("code_outline", "List the classes and functions in a source file with line numbers "
       "(precise for Python; best-effort for other languages). Use before reading big files.",
       S(path="string"))
    def code_outline(ctx: ToolContext, path: str):
        p = resolve_in_workspace(ctx.workspace, path)
        if not p.is_file():
            raise ToolError(f"No such file: {path}")
        src = p.read_text(errors="replace")
        if p.suffix == ".py":
            try:
                lines = python_outline(src)
            except SyntaxError as e:
                raise ToolError(f"Can't parse {path}: line {e.lineno}: {e.msg}")
        else:
            lines = [f"L{i} {line.strip()[:120]}" for i, line in enumerate(src.splitlines(), 1)
                     if _GENERIC_DEF.match(line)]
        return "\n".join(lines) or "No definitions found."

    @t("check_syntax", "Check a Python, JSON, XML or TOML file for syntax errors without running it.",
       S(path="string"))
    def check_syntax(ctx: ToolContext, path: str):
        p = resolve_in_workspace(ctx.workspace, path)
        if not p.is_file():
            raise ToolError(f"No such file: {path}")
        text = p.read_text(errors="replace")
        ext = p.suffix.lower()
        try:
            if ext == ".py":
                compile(text, path, "exec")
            elif ext == ".json":
                json.loads(text)
            elif ext in {".xml", ".svg"}:
                import xml.etree.ElementTree as ET
                ET.fromstring(text)
            elif ext == ".toml":
                import tomllib
                tomllib.loads(text)
            else:
                raise ToolError(f"No syntax checker for '{ext}' files (supported: .py .json .xml .svg .toml)")
        except SyntaxError as e:
            return f"SYNTAX ERROR in {path} line {e.lineno}: {e.msg}"
        except json.JSONDecodeError as e:
            return f"JSON ERROR in {path} line {e.lineno} col {e.colno}: {e.msg}"
        except ToolError:
            raise
        except Exception as e:
            return f"ERROR in {path}: {e}"
        return f"{path}: OK"

    @t("run_tests", "Run the project's Python tests (pytest if installed, else unittest) "
       "in the workspace or a sub-folder.",
       S(path="string?|Folder or file, default '.'", pattern="string?|Only tests matching this name (-k)"),
       risk="execute", requires_approval=True)
    def run_tests(ctx: ToolContext, path: str = ".", pattern: str | None = None):
        resolve_in_workspace(ctx.workspace, path)
        has_pytest = "exit code: 0" in run_process([sys.executable, "-c", "import pytest"], ctx)
        if has_pytest:
            argv = [sys.executable, "-m", "pytest", "-q", path] + (["-k", pattern] if pattern else [])
        else:
            argv = [sys.executable, "-m", "unittest", "discover", "-s", path, "-v"] + \
                   (["-k", pattern] if pattern else [])
        return run_process(argv, ctx, timeout=max(ctx.shell_timeout, 300))

    def git(ctx, *args):
        return run_process(["git", *args], ctx)

    @t("git_status", "Show git status (branch, staged/unstaged/untracked files) of the workspace repo.", S())
    def git_status(ctx: ToolContext):
        return git(ctx, "status", "--short", "--branch")

    @t("git_diff", "Show uncommitted changes (or staged ones with staged=true).",
       S(staged="boolean?", path="string?|Limit to this path"))
    def git_diff(ctx: ToolContext, staged: bool = False, path: str | None = None):
        args = ["diff"] + (["--cached"] if staged else []) + (["--", path] if path else [])
        return git(ctx, *args)

    @t("git_log", "Show recent commits.", S(count="integer?|Default 15"))
    def git_log(ctx: ToolContext, count: int = 15):
        return git(ctx, "log", f"-{count}", "--pretty=format:%h %ad %an  %s", "--date=short")

    @t("git_commit", "Stage files and create a commit in the workspace repo.",
       S(message="string", paths={"type": "array", "items": {"type": "string"},
                                  "description": "Files to stage; default all changes", "optional": True}),
       risk="write", requires_approval=True)
    def git_commit(ctx: ToolContext, message: str, paths: list | None = None):
        add = git(ctx, "add", *(paths or ["-A"]))
        if not add.startswith("exit code: 0"):
            return add
        return git(ctx, "commit", "-m", message)
