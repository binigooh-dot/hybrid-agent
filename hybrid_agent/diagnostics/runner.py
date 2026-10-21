"""[DIAGNOSTICS / runner] Run the safety drills and integrity checks; produce a report.

Every drill runs:
  * in its own temporary sandbox folder (deleted afterwards)
  * inside the network + process tripwires (see harness.py)
  * with a time limit, so a hanging defence is reported as FAIL instead of
    freezing the whole diagnostic
"""
from __future__ import annotations

import inspect
import json
import threading
import time
from dataclasses import asdict, dataclass

from .drills import DRILLS
from .harness import NetworkTripwire, ProcessTripwire, Sandbox
from .integrity import CHECKS

SLOW = {"exec.output_flood": 90, "fs.huge_file": 60, "exec.redos": 40}


@dataclass
class Result:
    key: str
    title: str
    category: str
    severity: str
    passed: bool
    detail: str
    seconds: float
    scenario: str = ""


def run_drill(d, timeout: float = 15.0) -> Result:
    box: dict = {}

    def target():
        try:
            with Sandbox() as sb, NetworkTripwire() as net, ProcessTripwire():
                kwargs = {"tripwire": net} if "tripwire" in inspect.signature(d.func).parameters else {}
                box["out"] = d.func(sb, **kwargs)
        except Exception as e:  # a crashing drill is a failing drill  # noqa: BLE001 - deliberate boundary: report the failure, never crash
            box["out"] = (False, f"drill crashed: {type(e).__name__}: {e}")

    start = time.monotonic()
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(SLOW.get(d.key, timeout))
    secs = time.monotonic() - start
    passed, detail = box.get("out", (False, f"HUNG: no result after {secs:.0f}s"))
    return Result(d.key, d.title, d.category, d.severity, bool(passed), detail, secs, d.scenario)


def run_all(only: str | None = None) -> dict:
    drills = [run_drill(d) for d in DRILLS if not only or d.key.startswith(only) or d.category == only]
    checks = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001 - deliberate boundary: report the failure, never crash
            ok, detail = False, f"{type(e).__name__}: {e}"
        checks.append({"name": name, "passed": ok, "detail": detail})
    return {"drills": [asdict(r) for r in drills], "integrity": checks,
            "passed": sum(r.passed for r in drills), "total": len(drills),
            "critical_failures": [r.key for r in drills if not r.passed and r.severity == "critical"],
            "time": time.strftime("%Y-%m-%d %H:%M:%S")}


def format_report(rep: dict, color: bool = True) -> str:
    g, r, y, b, d, x = ("\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[2m", "\033[0m") if color \
        else ("",) * 6
    lines = [f"{b}Safety drills{x}  ({rep['passed']}/{rep['total']} passed)", ""]
    cat = None
    for res in rep["drills"]:
        if res["category"] != cat:
            cat = res["category"]
            lines.append(f"{b}{cat}{x}")
        mark = f"{g}PASS{x}" if res["passed"] else f"{r}FAIL{x}"
        sev = f"{y}{res['severity']}{x}" if not res["passed"] else f"{d}{res['severity']}{x}"
        lines.append(f"  [{mark}] {res['title']:<58} {sev:<8} {d}{res['detail']}{x}")
    lines += ["", f"{b}Integrity checks{x}"]
    for c in rep["integrity"]:
        mark = f"{g}PASS{x}" if c["passed"] else f"{r}FAIL{x}"
        lines.append(f"  [{mark}] {c['name']:<16} {d}{c['detail']}{x}")
    crit = rep["critical_failures"]
    lines += ["", f"{r}CRITICAL failures: {', '.join(crit)}{x}" if crit else f"{g}No critical failures.{x}"]
    return "\n".join(lines)


def main(as_json: bool = False, only: str | None = None, save_dir=None) -> int:
    rep = run_all(only)
    print(json.dumps(rep, indent=2) if as_json else format_report(rep))
    if save_dir and not only:  # the knowledge suite shows the latest full run
        from pathlib import Path
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        (Path(save_dir) / "diagnostics-latest.json").write_text(json.dumps(rep, indent=2))
    ok = rep["passed"] == rep["total"] and all(c["passed"] for c in rep["integrity"])
    return 0 if ok else 1
