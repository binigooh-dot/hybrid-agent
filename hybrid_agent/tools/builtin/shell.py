"""[TOOLS / shell] Run shell commands and Python snippets.

Tools: run_shell, run_python, which

Both runners are subprocesses in the workspace directory with a timeout, and
both require user approval (unless auto-approve is on). This is NOT a
security sandbox - run the agent in a container/VM if you don't trust the model.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading

from ...security.guards import check_shell_command
from ..registry import S, ToolContext, ToolError, ToolRegistry

CATEGORY = "shell"


MAX_CAPTURE = 1_000_000  # bytes kept per stream; the rest is counted and discarded


def _drain(stream, sink: list, counter: list) -> None:
    """Read a pipe to EOF, keeping at most MAX_CAPTURE bytes (so a flood can't exhaust memory)."""
    kept = 0
    for chunk in iter(lambda: stream.read(65536), b""):
        counter[0] += len(chunk)
        if kept < MAX_CAPTURE:
            sink.append(chunk[: MAX_CAPTURE - kept])
            kept += len(sink[-1])
    stream.close()


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the process AND everything it started (shell=True spawns grandchildren)."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError):
        pass


def run_process(argv_or_cmd, ctx: ToolContext, shell: bool = False, stdin: str | None = None,
                timeout: int | None = None, env: dict | None = None) -> str:
    """Shared runner (also used by code/git tools). Returns a readable report.

    * runs in its own process group/session so a timeout kills the whole tree
    * output is drained by threads into bounded buffers (no memory blow-up)
    * stdin is closed after writing, so interactive prompts get EOF instead of hanging
    """
    limit = timeout or ctx.shell_timeout
    try:
        proc = subprocess.Popen(
            # Reviewed (B602): run_shell's purpose; approval + blocklist
            argv_or_cmd, shell=shell, cwd=ctx.workspace, env=env,  # nosec B602
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=(os.name == "posix"),
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0)
    except FileNotFoundError as e:
        raise ToolError(f"Program not found: {e.filename}") from None
    out: list[bytes] = []
    err: list[bytes] = []
    n_out, n_err = [0], [0]
    readers = [threading.Thread(target=_drain, args=(proc.stdout, out, n_out), daemon=True),
               threading.Thread(target=_drain, args=(proc.stderr, err, n_err), daemon=True)]
    for t in readers:
        t.start()
    try:
        if proc.stdin is not None:
            if stdin:
                proc.stdin.write(stdin.encode())
            proc.stdin.close()
    except BrokenPipeError:
        pass
    try:
        proc.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        proc.wait()
        for t in readers:
            t.join(2)
        raise ToolError(f"Timed out after {limit}s (process tree killed). Partial output:\n"
                        + b"".join(out).decode(errors="replace")[-2000:]) from None
    if os.name == "posix":
        # Background jobs ('cmd &') left in the command's process group are
        # stopped when the command finishes, so they can't pile up unseen.
        # Output they already wrote stays readable in the pipe buffer.
        _kill_tree(proc)
    for t in readers:
        t.join(5)

    def text(chunks, total):
        s = b"".join(chunks).decode(errors="replace")
        return s + (f"\n...[{total - MAX_CAPTURE} more bytes discarded]" if total > MAX_CAPTURE else "")
    parts = [f"exit code: {proc.returncode}"]
    if n_out[0]:
        parts.append("stdout:\n" + text(out, n_out[0]))
    if n_err[0]:
        parts.append("stderr:\n" + text(err, n_err[0]))
    return "\n".join(parts)


def register(reg: ToolRegistry) -> None:
    t = reg.group(CATEGORY)

    @t("run_shell", "Run a shell command in the workspace directory and return exit code, "
       "stdout and stderr. Non-interactive only.",
       S(command="string", timeout="integer?|Seconds, default from config"),
       risk="execute", requires_approval=True)
    def run_shell(ctx: ToolContext, command: str, timeout: int | None = None):
        check_shell_command(command)
        # Reviewed (B604): run_shell's purpose; approval + blocklist
        return run_process(command, ctx, shell=True, timeout=timeout)  # noqa: S604 - run_shell exists to run shell commands; approval + blocklist gate it  # nosec B604

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
