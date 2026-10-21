"""[CORE / home] The portable home folder: one directory holds everything the suite needs.

    HybridAgent/
    ├─ HybridAgent.exe       the launcher (or `hybrid-agent studio`)
    └─ home/
       ├─ settings.env       your settings (KEY=VALUE, edited from the Control panel)
       ├─ workspace/         the agents' files (+ .agent/ undo history)
       ├─ personas/ logs/    your characters; transcripts + audit log
       ├─ tasks/             the task queue, schedules and results
       ├─ models/            local model files (Ollama stores them here)
       └─ runtime/           the model engine, installed on demand

Where the home folder is:
  1. HYBRID_AGENT_HOME, if set
  2. running as the packaged app: the `home` folder next to the executable
  3. otherwise none - settings come from the environment / ./.env as before

Copy the whole HybridAgent folder to another drive or computer and everything
(models, tasks, personas, history) comes with it. Analogy: a camper van -
the kitchen, bed and luggage travel together.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .config import load_dotenv

FOLDERS = ("workspace", "personas", "logs", "tasks", "models", "runtime")
SETTINGS = "settings.env"
# settings.env keys the Control panel may change (everything else is edited by hand)
EDITABLE = ("LOCAL_MODEL", "LOCAL_PROVIDER", "LOCAL_BASE_URL", "AGENT_BACKEND", "AGENT_CONTACT", "SEARXNG_URL",
            "AGENT_SANDBOX", "AGENT_SAFE_MODE", "AGENT_MIN_FREE_MB", "LOCAL_NUM_CTX", "AGENT_AUTO_START_MODEL")


def frozen() -> bool:
    """True when running as the packaged executable (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def find_home() -> Path | None:
    if os.environ.get("HYBRID_AGENT_HOME"):
        return Path(os.environ["HYBRID_AGENT_HOME"]).expanduser().resolve()
    if frozen():
        return Path(sys.executable).resolve().parent / "home"
    return None


def apply_home(home: Path) -> Path:
    """Create the folders, load settings.env, and point every path setting inside `home`.

    Explicit environment variables still win (so a power user can override anything).
    """
    home = home.resolve()
    for name in FOLDERS:
        (home / name).mkdir(parents=True, exist_ok=True)
    settings = home / SETTINGS
    if not settings.exists():
        settings.write_text(
            "# Hybrid Agent settings - KEY=VALUE, one per line. The Control panel edits these for you.\n"
            "# All options: see .env.example in the project or docs/01_OFFLINE_REQUIREMENTS.md\n"
            "LOCAL_MODEL=qwen2.5:7b\n"
            "# AGENT_CONTACT=you@example.com   # sent to websites like Wikipedia so they know who to contact\n", encoding="utf-8")
    os.environ["HYBRID_AGENT_HOME"] = str(home)
    load_dotenv(settings)
    defaults = {"AGENT_WORKSPACE": home / "workspace", "AGENT_LOG_DIR": home / "logs",
                "AGENT_PERSONA_DIR": home / "personas", "OLLAMA_MODELS": home / "models"}
    for key, value in defaults.items():
        os.environ.setdefault(key, str(value))
    return home


def home_dir() -> Path | None:
    """The active home folder (after apply_home), else None."""
    h = os.environ.get("HYBRID_AGENT_HOME")
    return Path(h) if h else None


def state_dir() -> Path:
    """Where tasks/runtime/models live: the home folder, or ./ in a developer checkout."""
    return home_dir() or Path.cwd()


def read_settings(home: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    f = home / SETTINGS
    if f.exists():
        for raw in f.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.split(" #", 1)[0].strip()
    return out


def write_settings(home: Path, changes: dict[str, str]) -> dict[str, str]:
    """Update allowed keys in settings.env in place (comments and order kept); applies them now too."""
    bad = [k for k in changes if k not in EDITABLE]
    if bad:
        raise ValueError(f"not editable here: {', '.join(bad)}")
    for k, v in changes.items():
        if any(c in str(v) for c in "\r\n\0"):
            raise ValueError(f"{k}: value must be a single line")
    f = home / SETTINGS
    lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
    pending = {k: str(v).strip() for k, v in changes.items()}
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip().lstrip("# ").strip() if "=" in line else ""
        if key in pending:
            lines[i] = f"{key}={pending.pop(key)}" if changes[key] != "" else f"# {key}="
    lines += [f"{k}={v}" for k, v in pending.items() if v != ""]
    tmp = f.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(f)
    for k, v in changes.items():
        if v == "":
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    return read_settings(home)
