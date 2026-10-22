"""[APP] The one-click launcher behind HybridAgent.exe (and `hybrid-agent studio`).

    1. find / create the portable home folder (core/home.py) and load its settings
    2. if the app is already running, just reopen the browser - no second copy
    3. start the local model engine from the home folder, if installed (in the background)
    4. start the app (GUI + task scheduler) and open it in its own window

First run: the app offers one-click setup (engine + a model sized for this computer).
Closing this window (or Quit in Settings) stops the app, the scheduler and the
engine it started. Your files, tasks and models stay in the home folder.
"""
from __future__ import annotations

import argparse
import sys
import threading
import urllib.request
from pathlib import Path

BANNER = r"""
     .-----.
    /       \     Hybrid Agent
   |  o   o  |    your own AI helpers, on your computer
   |  \___/  |
    \       /
     '-----'
"""


def _console_title() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW("Hybrid Agent - keep this window open")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass


def _already_running(url_file: Path) -> str | None:
    try:
        url = url_file.read_text(encoding="utf-8").strip()
        base = url.split("/?", 1)[0]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(base + "/static/favicon.svg", timeout=2) as r:
            return url if r.status == 200 else None
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hybrid-agent studio", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", type=Path, help="home folder (default: next to the app, or ~/HybridAgent/home)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-engine", action="store_true", help="don't start the local model engine")
    args = ap.parse_args(argv)
    _console_title()
    print(BANNER)

    from .core.home import apply_home, find_home
    home = apply_home(args.home or find_home() or Path.home() / "HybridAgent" / "home")
    url_file = home / "runtime" / "studio.url"
    existing = _already_running(url_file)
    if existing:
        print("  Already running - opening it.")
        if not args.no_browser:
            from .gui.server import open_window
            open_window(existing)
        return 0

    from .core.config import Config
    from .security.guards import validate_workspace
    cfg = Config.from_env()
    try:
        cfg.validate()
        cfg.workspace = validate_workspace(cfg.workspace)
    except ValueError as e:
        print(f"  Settings problem: {e}\n  Fix it in {home / 'settings.env'} (or delete that file to start fresh)",
              file=sys.stderr)
        return 2
    cfg.workspace.mkdir(parents=True, exist_ok=True)
    print(f"  Your files: {home}")

    from .runtime import OllamaRuntime
    rt = OllamaRuntime(home, cfg.log_dir)
    if not args.no_engine and _env_true("AGENT_AUTO_START_MODEL", True) and cfg.local_provider == "ollama":
        if rt.binary() and not rt.running():
            def start_engine():
                try:
                    print(f"  Model engine: {rt.start()}")
                except RuntimeError as e:
                    print(f"  Model engine: {e}")
            threading.Thread(target=start_engine, daemon=True).start()
        elif not rt.binary():
            print("  Model engine: not installed yet - the app will offer one-click setup.")

    from .gui.server import serve
    return serve(cfg, port=args.port, open_browser=not args.no_browser, url_file=url_file, runtime=rt)


def _env_true(name: str, default: bool) -> bool:
    import os
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    sys.exit(main())
