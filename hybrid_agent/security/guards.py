"""[SECURITY / guards] Safety guards shared by every tool and entry point.

Analogy: the workspace is a fenced sandbox in a playground. File tools can
build anything inside the fence; `resolve_in_workspace` stops any path
(including ../ tricks and symlinks) that would climb over it. Shell commands
go past a bouncer (`check_shell_command`) that turns away the obviously
destructive ones, and anything risky still needs the user's y/N.

What lives here:
  validate_workspace   refuse /, home, system folders and protected paths as a workspace
  resolve_in_workspace keep every path inside the workspace
  writable_path        ... and keep file tools out of the agent's own .agent/ data
  ensure_disk_space    refuse writes when the disk is nearly full (keeps the OS healthy)
  check_shell_command  defence-in-depth blocklist for destructive commands
  safe_regex           refuse regexes that can take exponential time (ReDoS)
  read_text_limited    read a text file without risking memory exhaustion

None of this is a substitute for running untrusted work in a container/VM:
the blocklist catches mistakes and obvious attacks, not a determined adversary.
"""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from ..core.errors import ToolError

MAX_TEXT_BYTES = 20_000_000          # whole-file reads (edit, regex, csv...) above this are refused
MAX_REGEX_LEN = 1000

# ----------------------------------------------------------------- workspace
_SYSTEM_DIRS = ["/", "/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/opt", "/proc", "/root", "/sbin",
                "/sys", "/usr", "/var", "/System", "/Library", "/Applications", "/Users", "/home",
                "C:\\", "C:\\Windows", "C:\\Program Files", "C:\\Users"]


def validate_workspace(path: Path) -> Path:
    """Refuse workspaces that would make the sandbox meaningless.

    The workspace must be a dedicated folder: not the filesystem root, not a
    system folder, not your home folder itself, and not a parent of the home
    folder. Returns the resolved path.
    """
    p = Path(path).expanduser().resolve()
    home = Path.home().resolve()
    system = {Path(s).resolve() for s in _SYSTEM_DIRS if Path(s).exists() or os.name == "nt"}
    if p == home or p in home.parents:
        raise ValueError(f"Refusing workspace {p}: it contains your whole home folder. Use a dedicated "
                         "folder such as ~/agent-workspace")
    if p in system or p == p.parent:
        raise ValueError(f"Refusing workspace {p}: that is a system folder. Use a dedicated folder, "
                         "e.g. ./workspace")
    import tempfile

    from .protected import agent_paths, overlaps, protected_paths
    tmp = Path(tempfile.gettempdir()).resolve()
    # Temp folders may sit under a protected system path (macOS: /private/var), so a throwaway
    # temp workspace skips the SYSTEM/USER checks - but never the agent's own files.
    in_tmp = p == tmp or tmp in p.parents
    for q in agent_paths() if in_tmp else protected_paths():
        if overlaps(p, q):
            raise ValueError(f"Refusing workspace {p}: it overlaps protected path {q} (system files, "
                             "your keys/configs, or the agent itself). Use a dedicated folder.")
    return p


def resolve_in_workspace(workspace: Path, path: str) -> Path:
    """Turn a model-supplied path into an absolute path inside the workspace."""
    if not isinstance(path, str) or "\0" in path:
        raise ToolError("Invalid path.")
    root = workspace.resolve()
    p = Path(path).expanduser() if path.startswith("~") else Path(path)
    full = (p if p.is_absolute() else root / p).resolve()
    if full != root and root not in full.parents:
        raise ToolError(f"Path '{path}' is outside the workspace ({root}). "
                        "Use a path relative to the workspace.")
    return full


def writable_path(workspace: Path, path: str, min_free_mb: int = 0) -> Path:
    """resolve_in_workspace for tools that CHANGE files: the agent's own data
    (.agent/ - backups, memory, index) is off-limits, and the disk must have room."""
    full = resolve_in_workspace(workspace, path)
    internal = workspace.resolve() / ".agent"
    if full == internal or internal in full.parents:
        raise ToolError("The .agent folder holds the agent's backups and memory; file tools can't change it. "
                        "Use remember/forget or restore_backup instead.")
    ensure_disk_space(workspace, min_free_mb)
    return full


def ensure_disk_space(path: Path, min_free_mb: int = 1024) -> None:
    """Refuse to write when free space is below max(min_free_mb, 2% of the disk):
    a full disk can crash the operating system and corrupt files."""
    if min_free_mb <= 0:
        return
    try:
        import shutil
        u = shutil.disk_usage(path if path.exists() else path.parent)
    except OSError:
        return
    floor = max(min_free_mb * 1024 * 1024, int(u.total * 0.02))
    if u.free < floor:
        raise ToolError(f"Disk almost full ({u.free / 1e9:.1f} GB free; safety floor {floor / 1e9:.1f} GB). "
                        "Writing was refused to protect the system. Free some space first.")


def read_text_limited(path: Path, limit: int = MAX_TEXT_BYTES) -> str:
    """Read a whole text file, refusing files too large to hold safely in memory."""
    size = path.stat().st_size
    if size > limit:
        raise ToolError(f"{path.name} is {size / 1e6:.0f} MB; whole-file operations are limited to "
                        f"{limit / 1e6:.0f} MB. Use read_file with offset/limit or search_text instead.")
    return path.read_text(errors="replace", encoding="utf-8")


# --------------------------------------------------------------- shell guard
_PATTERNS = [
    (r"\bmkfs(\.\w+)?\b|\bmke2fs\b|\bwipefs\b|\bfdisk\b|\bparted\b", "formatting or partitioning a disk"),
    (r"\bdd\b[^|;&]*\bof=/dev/", "writing raw to a device"),
    (r">\s*/dev/(sd|hd|nvme|disk|mmcblk)", "overwriting a disk"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (r"\b(shutdown|reboot|halt|poweroff)\b|\binit\s+[06]\b|\bsystemctl\s+(poweroff|reboot|halt)", "power control"),
    (r"\b(curl|wget|fetch)\b[^|;&]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b", "piping a download into a shell"),
    (r"\bkill\s+(-\w+\s+)*-1\b|\bkillall\b|\bpkill\s+-9\s+-1", "killing all processes"),
    (r"\bcrontab\s+-r\b", "deleting all scheduled jobs"),
    (r"\b(del|erase)\s+/[sqf]|\brd\s+/s|\brmdir\s+/s|\bformat\s+[a-z]:|Remove-Item\b.*-Recurse",
     "recursive delete on Windows"),
    # --- hardware, firmware, kernel and system services
    (r"\b(modprobe|insmod|rmmod)\b", "loading/unloading kernel modules"),
    (r"\b(flashrom|fwupdmgr|efibootmgr|nvram|bless|grub-install|update-grub)\b", "firmware / boot loader change"),
    (r"\bsysctl\s+(-w\b|--write\b|\S+=)", "changing kernel parameters"),
    (r">\s*/(sys|proc/sys)/|\btee\s+(-a\s+)?/(sys|proc/sys)/", "writing to hardware/kernel interfaces"),
    (r"\bumount\b|\bmount\s+(-|/dev)|\bswapoff\b|\bhdparm\b|\bsmartctl\s+-s\b|\bwrmsr\b|\bsetpci\b|"
     r"\bcpufreq-set\b|\bnvidia-smi\s+-(pl|ac|lgc|rgc)\b", "changing disks, power or hardware settings"),
    (r"\b(systemctl|service)\s+(\S+\s+)?(stop|disable|mask|kill)\b|\blaunchctl\s+(unload|remove|bootout)\b",
     "stopping or disabling system services"),
    (r"\b(diskpart|bcdedit|vssadmin|wbadmin)\b|\breg\s+(delete|add)\b|\bwmic\s+shadowcopy",
     "Windows disk/boot/registry change"),
    (r"\b(passwd|chpasswd|usermod|userdel|useradd|visudo)\b", "changing user accounts"),
    (r"\biptables\s+-[FX]\b|\bufw\s+disable\b|\bnetsh\s+advfirewall\s+set\s+\S+\s+state\s+off",
     "disabling the firewall"),
    (r"\bfind\b.*\s-delete\b", "find -delete"),
    (r"\bchmod\b.*\s-R\b|\bchown\b.*\s-R\b|\bchgrp\b.*\s-R\b|\bchmod\s+-R|\bchown\s+-R",
     "recursive permission change"),
]
_DANGEROUS_TARGETS = re.compile(r"""^(/.*|~.*|\$\{?HOME\}?.*|\.\.(/.*)?|\*|/\*)$""")


def _segments(command: str) -> list[list[str]]:
    """Split a command line into simple commands (on ; && || | & newlines) and tokenise each."""
    out = []
    for part in re.split(r";|&&|\|\||\||&|\n", command):
        try:
            toks = shlex.split(part, posix=True)
        except ValueError:
            toks = part.split()
        if toks:
            out.append(toks)
    return out


def _is_recursive_rm(tokens: list[str]) -> list[str] | None:
    """If tokens are `[sudo] [/bin/]rm ... -r...`, return the targets."""
    while tokens and tokens[0] in {"sudo", "doas", "nice", "nohup", "command", "env", "builtin"}:
        tokens = tokens[1:]
    if not tokens or os.path.basename(tokens[0]) not in {"rm", "rmdir", "shred", "unlink"}:
        return None
    flags = [t for t in tokens[1:] if t.startswith("-")]
    targets = [t for t in tokens[1:] if not t.startswith("-")]
    recursive = any(f in {"--recursive", "-R", "-r"} or (not f.startswith("--") and ("r" in f or "R" in f))
                    for f in flags)
    return targets if (recursive or os.path.basename(tokens[0]) == "shred") else None


def check_shell_command(command: str, workspace: Path | None = None) -> None:
    """Raise ToolError for commands that look destructive beyond the workspace.

    Recursive deletes are refused when ANY target is absolute, in the home
    folder, a parent (..), or a bare wildcard. Deleting inside the workspace
    (`rm -rf build/`, `rm -rf ./dist`) is allowed.
    """
    for pattern, why in _PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            raise ToolError(f"Blocked command ({why}). If this is really needed, ask the user to run it "
                            "themselves.")
    from .protected import protected_targets
    hits = protected_targets(command, workspace)
    if hits:
        raise ToolError(f"Blocked command: it would modify protected path(s) {', '.join(hits)} (system files, "
                        "your keys/configs, or the agent's own files).")
    if workspace is not None and re.search(r"(^|[\s/'\"])\.agent\b", command) and \
            re.search(r"\b(rm|mv|cp|tee|truncate|shred|sed\s+-i|chmod|ln)\b|>", command):
        raise ToolError("Blocked command: the .agent folder holds backups and memory and can't be changed by commands.")
    for tokens in _segments(command):
        targets = _is_recursive_rm(tokens)
        if targets is None:
            continue
        for t in targets:
            norm = t.strip().rstrip("/") or "/"
            if _DANGEROUS_TARGETS.match(norm) or _DANGEROUS_TARGETS.match(t):
                raise ToolError(f"Blocked command (recursive delete of '{t}' outside the workspace). "
                                "Recursive deletes may only target paths inside the workspace.")


# --------------------------------------------------------------- regex guard
# Nested quantifiers such as (a+)+, (a*)*, (a|aa)+ are the classic catastrophic-
# backtracking shapes (ReDoS). Python's regex engine holds the GIL while
# matching, so a thread timeout cannot interrupt it. Risky-looking patterns are
# therefore run in a separate process that can be killed (see regex_worker.py);
# ordinary patterns run in-process at full speed.
_NESTED_QUANT = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)\s*(?:[+*]|\{\d*,?\d*\})")
_ALT_QUANT = re.compile(r"\((?:[^()\\]|\\.)*\|(?:[^()\\]|\\.)*\)\s*[+*]")
REGEX_TIMEOUT = 5


def compile_regex(pattern: str, flags: int = 0) -> tuple[re.Pattern, bool]:
    """Compile a model-supplied regex. Returns (compiled, risky); when risky is
    True, callers must run the match through run_regex_isolated()."""
    if not isinstance(pattern, str) or len(pattern) > MAX_REGEX_LEN:
        raise ToolError(f"Regex too long (max {MAX_REGEX_LEN} characters).")
    try:
        rx = re.compile(pattern, flags)
    except re.error as e:
        raise ToolError(f"Bad regex: {e}") from None
    return rx, bool(_NESTED_QUANT.search(pattern) or _ALT_QUANT.search(pattern))


def run_regex_isolated(op: str, payload: dict, timeout: float = REGEX_TIMEOUT):
    """Run a regex operation in a child Python process that is killed on timeout."""
    import json
    import subprocess
    pkg_root = str(Path(__file__).resolve().parent.parent.parent)
    code = (f"import sys; sys.path.insert(0, {pkg_root!r}); "
            "from hybrid_agent.security.regex_worker import main; main()")
    try:
        from ..core.pyexe import internal_command
        r = subprocess.run([*internal_command(), "-X", "utf8", "-I", "-c", code], input=json.dumps({"op": op, **payload}),
                           capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise ToolError(f"Regex gave up after {timeout}s: the pattern backtracks catastrophically on this "
                        "input (nested repetition like (a+)+). Simplify the pattern.") from None
    if r.returncode != 0:
        raise ToolError(f"Regex worker failed: {r.stderr.strip()[-300:]}")
    return json.loads(r.stdout)
