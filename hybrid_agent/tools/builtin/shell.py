"""[TOOLS / shell] Run shell commands and Python snippets.

Tools: run_shell, run_python, which

Both runners are subprocesses in the workspace directory with a timeout, and
both require user approval (unless auto-approve is on). This is NOT a
security sandbox - run the agent in a container/VM if you don't trust the model.
"""
from __future__ import annotations

import shutil
import subprocess
import sys

from ...core.safety import check_shell_command
from ..registry import S, ToolContext, ToolError, ToolRegistry

CATEGORY = "shell"


def run_process(argv_or_cmd, ctx: ToolContext, shell: bool = False, stdin: str | None = None,
                timeout: int | None = None) -> str:
    """Shared runner (also used by code/git tools). Returns a readable report."""
    try:
        r = subprocess.run(argv_or_cmd, shell=shell, cwd=ctx.workspace, input=stdin,
                           capture_output=True, text=True, timeout=timeout or ctx.shell_timeout)
    except subprocess.TimeoutExpired:
        raise ToolError(f"Timed out after {timeout or ctx.shell_timeout}s")
    except FileNotFoundError as e:
        raise ToolError(f"Program not found: {e.filename}")
    parts = [f"exit code: {r.returncode}"]
    if r.stdout:
        parts.append("stdout:\n" + r.stdout)
    if r.stderr:
        parts.append("stderr:\n" + r.stderr)
    return "\n".join(parts)


def register(reg: ToolRegistry) -> None:
    t = lambda *a, **k: reg.tool(*a, category=CATEGORY, **k)  # noqa: E731

    @t("run_shell", "Run a shell command in the workspace directory and return exit code, "
       "stdout and stderr. Non-interactive only.",
       S(command="string", timeout="integer?|Seconds, default from config"),
       risk="execute", requires_approval=True)
    def run_shell(ctx: ToolContext, command: str, timeout: int | None = None):
        check_shell_command(command)
        return run_process(command, ctx, shell=True, timeout=timeout)

    @t("run_python", "Run a Python 3 snippet in a fresh interpreter (cwd = workspace). "
       "Print what you want to see.",
       S(code="string", timeout="integer?|Seconds, default from config"),
       risk="execute", requires_approval=True)
    def run_python(ctx: ToolContext, code: str, timeout: int | None = None):
        return run_process([sys.executable, "-I", "-"], ctx, stdin=code, timeout=timeout)

    @t("which", "Check whether command-line programs are installed, and where.",
       S(programs={"type": "array", "items": {"type": "string"}}))
    def which(ctx: ToolContext, programs: list):
        return "\n".join(f"{p}: {shutil.which(p) or 'NOT FOUND'}" for p in programs)
