"""[SECURITY / protected] Paths that must never be modified: the OS, the hardware, your secrets, the agent itself.

Three groups:
  SYSTEM   - operating system, boot loader, devices, firmware/hardware interfaces
  USER     - keys, credentials and shell/startup configs in your home folder
  AGENT    - the agent's own code, config, task queue, model engine and models

Enforced in three places:
  * validate_workspace refuses a workspace that overlaps any protected path
  * check_shell_command refuses modifying commands that name a protected path
  * the strict sandbox (sandbox.py) makes the whole system read-only and hides
    your home folder, so even a cleverly-written command can't reach them

Analogy: the electrical panel and the safe in a house. Guests (the agent) may
use any room you give them, but those two are locked no matter what.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent          # hybrid_agent/
PROJECT_DIR = PKG_DIR.parent                               # checkout or site-packages

SYSTEM = ["/bin", "/boot", "/dev", "/efi", "/etc", "/lib", "/lib32", "/lib64", "/libx32", "/opt", "/proc",
          "/root", "/sbin", "/snap", "/sys", "/usr", "/var", "/System", "/Library", "/private/etc",
          "/private/var", "/Applications", "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
          "C:\\ProgramData", "C:\\Boot", "C:\\EFI"]
USER = [".ssh", ".gnupg", ".aws", ".azure", ".config/gcloud", ".kube", ".docker", ".netrc", ".pgpass",
        ".git-credentials", ".gitconfig", ".bashrc", ".bash_profile", ".profile", ".zshrc", ".zprofile",
        ".config/fish", ".pam_environment", ".xinitrc", ".config/autostart", ".local/share/keyrings",
        "Library/Keychains", ".mozilla", ".config/google-chrome", ".config/chromium", ".anthropic",
        ".config/anthropic", ".password-store", "AppData/Roaming/Microsoft"]


def agent_paths(extra: list[Path] | None = None) -> list[Path]:
    """The agent's own critical files: code, config, and (portable mode) the home folder's
    settings, task queue, model engine and model files. The home's workspace is NOT protected."""
    out = [PKG_DIR, PROJECT_DIR / ".env", PROJECT_DIR / "pyproject.toml"]
    if getattr(sys, "frozen", False):          # the packaged app: HybridAgent.exe and its _internal folder
        exe = Path(sys.executable).resolve()
        out += [exe, exe.parent / "_internal", exe.parent / "MANIFEST.sha256"]
    home = os.environ.get("HYBRID_AGENT_HOME")
    if home:
        out += [Path(home) / n for n in ("settings.env", "tasks", "runtime", "models")]
    return [p.resolve() for p in out + list(extra or [])]


def protected_paths(extra: list[Path] | None = None) -> list[Path]:
    home = Path.home()
    paths = [Path(p) for p in SYSTEM if os.name == "nt" or not p.startswith("C:")]
    paths += [home / p for p in USER]
    return [p.resolve() for p in paths] + agent_paths(extra)   # resolve(strict=False): works for missing paths too


def overlaps(path: Path, protected: Path) -> bool:
    """True if `path` is inside `protected`, or contains it."""
    try:
        path, protected = path.resolve(), protected.resolve()
    except OSError:
        return False
    return path == protected or protected in path.parents or path in protected.parents


# ---------------------------------------------------------- command scanning
_MODIFYING = re.compile(
    r"\b(rm|rmdir|mv|cp|dd|tee|truncate|shred|unlink|ln|install|rsync|chmod|chown|chgrp|chattr|touch|"
    r"mkdir|sed\s+-i|perl\s+-pi|patch|tar\s+-?x|unzip|git\s+(clean|checkout|reset))\b|>>?|>\|")
_TOKEN_SPLIT = re.compile(r"[\s'\"=;&|()<>]+")


def _token_path(tok: str, home: str, workspace: Path | None) -> Path | None:
    """The path a command-line token names (None for flags, plain words, /dev/null-style and /tmp paths)."""
    if not tok or tok.startswith("-") or ("/" not in tok and not tok.startswith(("~", "$HOME", "${HOME}"))):
        return None
    expanded = tok.replace("${HOME}", home).replace("$HOME", home)
    if expanded.startswith("~"):
        expanded = home + expanded[1:]
    if expanded in {"/dev/null", "/dev/stdout", "/dev/stderr"} or expanded.startswith("/tmp/"):  # noqa: S108  # nosec B108 - only skips scanning
        return None
    rooted = os.path.isabs(expanded) or expanded.startswith(("/", "\\"))   # Windows: "/etc" is rooted, not relative
    p = Path(expanded) if rooted else ((workspace or Path.cwd()) / expanded)
    try:
        return p.resolve()
    except OSError:
        return None


def protected_targets(command: str, workspace: Path | None = None, extra: list[Path] | None = None) -> list[str]:
    """Protected paths a *modifying* shell command mentions (empty if none / read-only command)."""
    if not _MODIFYING.search(command):
        return []
    home, prot = str(Path.home()), protected_paths(extra)
    ws = workspace.resolve() if workspace else None
    hits = []
    for tok in _TOKEN_SPLIT.split(command):
        target = _token_path(tok, home, workspace)
        # The workspace is the agent's own folder: never "protected", even when it sits under a protected
        # system path (macOS temp folders live in /private/var/folders/...). `..` escapes resolve outside it.
        if target is None or (ws and (target == ws or ws in target.parents)):
            continue
        if any(target == q or q in target.parents for q in prot):
            hits.append(tok)
    return hits
