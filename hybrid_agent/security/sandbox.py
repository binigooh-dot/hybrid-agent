"""[SECURITY / sandbox] Hard, kernel-enforced limits for every command the agent runs.

Modes (AGENT_SANDBOX):
  strict  Linux: bubblewrap (`bwrap`) - the whole system is mounted READ-ONLY, your
          home folder is replaced by an empty folder (your files and keys are
          invisible), /tmp is private, and only the workspace is writable. The
          agent's backups/audit data inside the workspace stay read-only.
          macOS: sandbox-exec with a profile that only allows writes to the
          workspace and temp folders.
  limits  No filesystem isolation, but kernel resource limits still apply.
  auto    strict when available, otherwise limits (default).
  off     Nothing extra (not recommended).

Always (except off): secret-looking environment variables (API keys, tokens…)
are removed, and on POSIX these kernel limits apply to the command and all its
children: CPU time, memory, size of any file written, open files, core dumps.

AGENT_REQUIRE_SANDBOX=1 refuses to run commands at all when strict isolation
is unavailable.

Analogy: a glovebox in a lab. The agent can work inside it with full dexterity,
but nothing it does can touch the rest of the room.
"""
from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import ToolError

SECRET_NAME = re.compile(r"key|token|secret|pass|pwd|auth|cred|cookie|session|private", re.I)
# Variables that make programs load or run other code - never passed to commands.
CODE_INJECTION_VARS = {"LD_PRELOAD", "LD_AUDIT", "DYLD_INSERT_LIBRARIES", "GIT_EXTERNAL_DIFF", "GIT_SSH",
                       "GIT_SSH_COMMAND", "GIT_ASKPASS", "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_PROXY_COMMAND",
                       "GIT_CONFIG_PARAMETERS", "PYTHONSTARTUP", "BASH_ENV", "ENV", "PROMPT_COMMAND"}
# git settings passed through the environment (they can set core.fsmonitor etc.) - dropped as a family
GIT_ENV_CONFIG = re.compile(r"^GIT_CONFIG_(COUNT|KEY_\d+|VALUE_\d+)$")


@dataclass(frozen=True)
class Limits:
    cpu_seconds: int = 600            # total CPU time
    memory_mb: int = 4096             # heap/data size
    file_mb: int = 2048               # largest single file a command may write
    open_files: int = 1024


def clean_env(extra: dict | None = None) -> dict:
    """The parent's environment minus secrets and code-injection variables."""
    env = {k: v for k, v in os.environ.items()
           if not SECRET_NAME.search(k) and k not in CODE_INJECTION_VARS and not GIT_ENV_CONFIG.match(k)}
    env.update(extra or {})
    return env


# A tiny launcher: set kernel limits, then exec the real command. Limits apply
# before the command's first instruction and are inherited by every child it
# starts. (Safer than subprocess's preexec_fn, which can deadlock with threads.)
_LIMITER = (
    "import os,sys,resource as r\n"
    "for n,v in zip(('RLIMIT_CPU','RLIMIT_DATA','RLIMIT_FSIZE','RLIMIT_NOFILE','RLIMIT_CORE'),"
    "map(int,sys.argv[1:6])):\n"
    " res=getattr(r,n);s,h=r.getrlimit(res);v=v if h==r.RLIM_INFINITY else min(v,h)\n"
    " try:r.setrlimit(res,(v,v))\n"
    " except (ValueError,OSError):pass\n"
    "os.execvp(sys.argv[6],sys.argv[6:])"
)


def _limiter_prefix(limits: Limits) -> list[str]:
    return [sys.executable, "-I", "-S", "-c", _LIMITER, str(limits.cpu_seconds),
            str(limits.memory_mb * 1024 * 1024), str(limits.file_mb * 1024 * 1024), str(limits.open_files), "0"]


@functools.lru_cache(maxsize=1)
def strict_available() -> str | None:
    """'bwrap' / 'sandbox-exec' if a working isolation tool exists, else None (probed once)."""
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        try:
            r = subprocess.run(["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
                                "--die-with-parent", "true"], capture_output=True, timeout=10, check=False)
            if r.returncode == 0:
                return "bwrap"
        except (OSError, subprocess.TimeoutExpired):
            pass
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return "sandbox-exec"
    return None


def _bwrap_prefix(workspace: Path) -> list[str]:
    ws = str(workspace.resolve())
    home = str(Path.home().resolve())
    args = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
            "--tmpfs", "/tmp", "--tmpfs", home]  # noqa: S108  # nosec B108 - a PRIVATE empty /tmp inside the sandbox
    gitconfig = Path(home) / ".gitconfig"
    if gitconfig.is_file():                                           # git needs your name/email to commit
        args += ["--ro-bind", str(gitconfig), str(gitconfig)]
    args += ["--bind", ws, ws]                                        # the only writable place
    internal = workspace / ".agent"
    if internal.is_dir():                                             # backups + audit stay read-only
        args += ["--ro-bind", str(internal), str(internal)]
    args += ["--unshare-pid", "--die-with-parent", "--new-session", "--setenv", "HOME", home,
             "--chdir", ws]
    return args


def _macos_prefix(workspace: Path) -> list[str]:
    ws = str(workspace.resolve()).replace('"', "")
    profile = ('(version 1)(allow default)(deny file-write*)'
               f'(allow file-write* (subpath "{ws}") (subpath "/private/tmp") (subpath "/private/var/folders")'
               ' (literal "/dev/null") (literal "/dev/tty"))'
               f'(deny file-write* (subpath "{ws}/.agent"))')
    return ["sandbox-exec", "-p", profile]


DEFAULT_LIMITS = Limits()


def wrap(argv_or_cmd, shell: bool, workspace: Path, mode: str = "auto", require: bool = False,
         limits: Limits = DEFAULT_LIMITS) -> tuple[list[str] | str, dict, bool, str]:
    """Return (command, env, use_shell, mode_used) ready for subprocess.Popen."""
    if mode not in {"auto", "strict", "limits", "off"}:
        raise ToolError(f"unknown sandbox mode {mode!r}")
    tool = strict_available() if mode in {"auto", "strict"} else None
    if (mode == "strict" or require) and not tool:
        raise ToolError("A strict sandbox is required but unavailable. Install bubblewrap (Linux: "
                        "`sudo apt install bubblewrap`), or set AGENT_REQUIRE_SANDBOX=0 / AGENT_SANDBOX=limits.")
    if mode == "off":
        return argv_or_cmd, dict(os.environ), shell, "off"
    if os.name != "posix":          # Windows: environment scrubbing only
        return argv_or_cmd, clean_env(), shell, "env-only"
    argv = ["/bin/sh", "-c", argv_or_cmd] if shell else list(argv_or_cmd)
    if tool == "bwrap":
        argv = _bwrap_prefix(workspace) + argv
    elif tool == "sandbox-exec":
        argv = _macos_prefix(workspace) + argv
    return _limiter_prefix(limits) + argv, clean_env(), False, f"strict ({tool})" if tool else "limits"
