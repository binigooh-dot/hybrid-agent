"""Safety guards shared by the tools.

Analogy: the workspace is a fenced sandbox in a playground. File tools can
build anything inside the fence, but `resolve_in_workspace` stops any path
(including ../ tricks and symlinks) that would climb over it. Shell commands
go past a bouncer (`check_shell_command`) that turns away the obviously
destructive ones, and anything risky still needs the user's y/N.
"""
from __future__ import annotations

import re
from pathlib import Path

from .tools.registry import ToolError

_DANGEROUS = [
    (r"\brm\s+-[a-z]*r[a-z]*f?\s+(/|~|\$HOME)(\s|$)", "recursive delete of / or home"),
    (r"\bmkfs(\.\w+)?\b", "formatting a filesystem"),
    (r"\bdd\b.*\bof=/dev/", "writing raw to a device"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "fork bomb"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "power control"),
    (r">\s*/dev/sd[a-z]", "overwriting a disk"),
    (r"\bchmod\s+-R\s+777\s+/", "chmod 777 on /"),
    (r"(curl|wget)[^|]*\|\s*(sudo\s+)?(ba|z)?sh\b", "piping a download into a shell"),
]


def resolve_in_workspace(workspace: Path, path: str) -> Path:
    """Turn a model-supplied path into an absolute path inside the workspace."""
    root = workspace.resolve()
    p = Path(path)
    full = (p if p.is_absolute() else root / p).resolve()
    if full != root and root not in full.parents:
        raise ToolError(f"Path '{path}' is outside the workspace ({root}). "
                        "Use a path relative to the workspace.")
    return full


def check_shell_command(command: str) -> None:
    for pattern, why in _DANGEROUS:
        if re.search(pattern, command):
            raise ToolError(f"Blocked command ({why}). If this is really needed, "
                            "ask the user to run it themselves.")
