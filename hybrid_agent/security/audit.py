"""[SECURITY / audit] Append-only record of every action that changes something, plus integrity checks.

audit.jsonl   one line per write/execute tool call: when, which agent, which tool,
              (redacted) arguments, and whether it succeeded. Kept outside the
              workspace, so the agent's own tools can't edit it.

Integrity manifest: SHA-256 of every file in the package, written at release
time (scripts/build_release.py -> hybrid_agent/MANIFEST.sha256). verify_manifest()
then detects any changed, missing or added file - corruption or tampering.
The packaged app (scripts/build_exe.py) covers its whole folder - HybridAgent.exe
and _internal/ - in HybridAgent/MANIFEST.sha256; your home/ folder is never included.

Analogy: a flight recorder (audit log) and a tamper-evident seal (manifest).
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from pathlib import Path

from .redact import redact_obj

PKG = Path(__file__).resolve().parent.parent
MANIFEST = PKG / "MANIFEST.sha256"
SKIP_TOP = {"home"}                       # the packaged app's user data is never part of the manifest


def _root() -> Path:
    """The packaged app's folder, or the hybrid_agent package for a normal install."""
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else PKG
_LOCK = threading.Lock()


def record(log_dir: Path | None, agent: str, tool: str, risk: str, args: dict, ok: bool, note: str = "") -> None:
    if log_dir is None:
        return
    entry = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "agent": agent, "tool": tool, "risk": risk, "ok": ok,
             "args": redact_obj({k: (v[:300] if isinstance(v, str) else v) for k, v in args.items()}),
             "note": note[:300]}
    with _LOCK:
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "audit.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")


# ----------------------------------------------------------- integrity
def compute_manifest(root: Path | None = None) -> dict[str, str]:
    root = root or _root()
    files = (p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts
             and p.suffix != ".pyc" and p.name != MANIFEST.name and p.relative_to(root).parts[0] not in SKIP_TOP)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def write_manifest(root: Path | None = None) -> Path:
    root = root or _root()
    path = root / MANIFEST.name
    path.write_text("".join(f"{h}  {n}\n" for n, h in sorted(compute_manifest(root).items())), encoding="utf-8")
    return path


def verify_manifest(root: Path | None = None) -> tuple[str, str]:
    """('ok' | 'absent' | 'changed', detail)."""
    root = root or _root()
    path = root / MANIFEST.name
    if not path.exists():
        return "absent", "no release manifest (development checkout)"
    want = {n: h for h, n in (line.split("  ", 1) for line in path.read_text(encoding="utf-8").splitlines() if "  " in line)}
    have = compute_manifest(root)
    changed = sorted(n for n in want if have.get(n) != want[n])
    added = sorted(set(have) - set(want))
    if not changed and not added:
        return "ok", f"{len(want)} files match the release manifest"
    parts = ([f"changed/missing: {', '.join(changed[:5])}"] if changed else []) + \
            ([f"unexpected: {', '.join(added[:5])}"] if added else [])
    return "changed", "; ".join(parts)
