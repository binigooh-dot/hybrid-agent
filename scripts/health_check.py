"""[SCRIPTS / qa] One command for a full code-health check, with a scorecard.

    python scripts/health_check.py            # everything available
    python scripts/health_check.py --fast     # skip slow steps (drills, browser, coverage)

Runs (each is skipped with a note if its tool isn't installed):
  tests      python -m unittest  (all offline)
  drills     python -m hybrid_agent diagnose   (safety fire drills)
  ruff       lint + security rules            pip install ruff
  mypy       static types                     pip install mypy
  bandit     security scan (medium+)          pip install bandit
  vulture    dead code                        pip install vulture
  vermin     minimum Python version (3.10)    pip install vermin
  radon      complexity (nothing rated D-F)   pip install radon
  coverage   test coverage                    pip install coverage
  browser    GUI smoke test in Chromium       pip install playwright
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def run(cmd: list[str], ok=lambda r: r.returncode == 0, timeout: int = 900):
    start = time.monotonic()
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return False, "timed out", time.monotonic() - start
    out = (r.stdout + r.stderr).strip().splitlines()
    return ok(r), (out[-1] if out else ""), time.monotonic() - start


def has(module: str) -> bool:
    return subprocess.run([PY, "-c", f"import {module}"], capture_output=True, check=False).returncode == 0


def main() -> int:
    fast = "--fast" in sys.argv
    steps = [
        ("tests", None, [PY, "-m", "unittest", "discover", "-s", "tests", "-t", "."], None),
        ("ruff", "ruff", ["ruff", "check", "."], None),
        ("mypy", "mypy", [PY, "-m", "mypy", "hybrid_agent"], None),
        ("bandit", "bandit", ["bandit", "-r", "hybrid_agent", "-ll", "-q"], None),
        ("vulture", "vulture", ["vulture", "hybrid_agent", "scripts", "--min-confidence", "70"],
         lambda r: r.returncode == 0 and not r.stdout.strip()),
        ("vermin 3.10", "vermin", ["vermin", "--no-tips", "-t=3.10-", "--violations", "hybrid_agent"], None),
        ("radon <= C", "radon", ["radon", "cc", "hybrid_agent", "-nd"], lambda r: not r.stdout.strip()),
    ]
    if not fast:
        steps += [
            ("safety drills", None, [PY, "-m", "hybrid_agent", "diagnose"], None),
            ("coverage", "coverage", [PY, "-m", "coverage", "run", "--branch", "--source=hybrid_agent",
                                      "-m", "unittest", "discover", "-s", "tests", "-t", "."], None),
            ("browser GUI", "playwright", [PY, "scripts/ui_smoke.py"], None),
        ]
    rows, failed = [], 0
    for name, tool, cmd, check in steps:
        if tool and not (shutil.which(tool) or has(tool)):
            rows.append(("SKIP", name, f"pip install {tool}", 0.0))
            continue
        ok, last, secs = run(cmd, check or (lambda r: r.returncode == 0))
        if name == "coverage" and ok:
            _, last, _ = run([PY, "-m", "coverage", "report", "--format=total"])
            last = f"{last}% of lines/branches covered"
        rows.append(("PASS" if ok else "FAIL", name, last[:90], secs))
        failed += not ok
    print("\nCode health scorecard\n")
    for status, name, detail, secs in rows:
        print(f"  [{status}] {name:<14} {secs:6.1f}s  {detail}")
    print(f"\n{'All checks passed.' if not failed else f'{failed} check(s) failed.'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
