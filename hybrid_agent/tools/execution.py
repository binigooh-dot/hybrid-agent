"""Code execution tools: shell commands and Python snippets.

Both run as subprocesses in the workspace directory with a timeout, and both
require user approval (unless auto-approve is on). This is NOT a security
sandbox - run the agent in a container/VM if you don't trust the model.
"""
from __future__ import annotations

import subprocess
import sys

from ..safety import check_shell_command
from .registry import ToolContext, ToolError, ToolRegistry


def _run(argv_or_cmd, ctx: ToolContext, shell: bool, stdin: str | None = None) -> str:
    try:
        r = subprocess.run(argv_or_cmd, shell=shell, cwd=ctx.workspace, input=stdin,
                           capture_output=True, text=True, timeout=ctx.shell_timeout)
    except subprocess.TimeoutExpired:
        raise ToolError(f"Timed out after {ctx.shell_timeout}s")
    parts = [f"exit code: {r.returncode}"]
    if r.stdout:
        parts.append("stdout:\n" + r.stdout)
    if r.stderr:
        parts.append("stderr:\n" + r.stderr)
    return "\n".join(parts)


def register(reg: ToolRegistry) -> None:

    @reg.tool("run_shell",
              "Run a shell command in the workspace directory and return exit code, "
              "stdout and stderr. Non-interactive only.",
              {"type": "object", "properties": {"command": {"type": "string"}},
               "required": ["command"]},
              requires_approval=True)
    def run_shell(ctx: ToolContext, command: str):
        check_shell_command(command)
        return _run(command, ctx, shell=True)

    @reg.tool("run_python",
              "Run a Python 3 snippet in a fresh interpreter (cwd = workspace). "
              "Print what you want to see.",
              {"type": "object", "properties": {"code": {"type": "string"}},
               "required": ["code"]},
              requires_approval=True)
    def run_python(ctx: ToolContext, code: str):
        return _run([sys.executable, "-I", "-"], ctx, shell=False, stdin=code)
