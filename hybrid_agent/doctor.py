"""`python -m hybrid_agent doctor` - checks everything needed to run.

Separates MANDATORY checks (needed to run with no API key) from OPTIONAL ones
(Claude). Exit code 0 means the agent can run key-free.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import urllib.request

from .config import Config, claude_credentials_present

OK, WARN, FAIL = "PASS", "WARN", "FAIL"


def _get_json(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def run_checks(cfg: Config) -> list[tuple[str, str, str, bool]]:
    """Returns rows of (status, check, detail, mandatory)."""
    rows: list[tuple[str, str, str, bool]] = []

    # 1. Python
    ok = sys.version_info >= (3, 10)
    rows.append((OK if ok else FAIL, "Python >= 3.10", sys.version.split()[0], True))

    # 2. Local model server
    server_ok, models = False, []
    try:
        if cfg.local_provider == "ollama":
            data = _get_json(cfg.local_base_url.rstrip("/") + "/api/tags")
            models = [m["name"] for m in data.get("models", [])]
        else:
            data = _get_json(cfg.local_base_url.rstrip("/") + "/v1/models")
            models = [m["id"] for m in data.get("data", [])]
        server_ok = True
        rows.append((OK, f"Local server ({cfg.local_provider})", cfg.local_base_url, True))
    except Exception as e:
        hint = " - install Ollama and run `ollama serve`" if cfg.local_provider == "ollama" else ""
        rows.append((FAIL, f"Local server ({cfg.local_provider})", f"{cfg.local_base_url}: {e}{hint}", True))

    # 3. Model pulled
    if server_ok:
        want = cfg.local_model
        have = any(m == want or m == f"{want}:latest" or m.split(":")[0] == want for m in models)
        rows.append((OK if have else FAIL, f"Local model '{want}'",
                     "available" if have else f"not found; run `ollama pull {want}` "
                     f"(have: {', '.join(models) or 'none'})", True))
    else:
        rows.append((FAIL, f"Local model '{cfg.local_model}'", "skipped (server down)", True))

    # 4. Workspace writable
    try:
        cfg.workspace.mkdir(parents=True, exist_ok=True)
        probe = cfg.workspace / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        rows.append((OK, "Workspace writable", str(cfg.workspace.resolve()), True))
    except OSError as e:
        rows.append((FAIL, "Workspace writable", str(e), True))

    # 5. Optional: Ollama CLI on PATH (handy, not required if server runs elsewhere)
    if cfg.local_provider == "ollama":
        rows.append((OK if shutil.which("ollama") else WARN, "`ollama` CLI on PATH",
                     shutil.which("ollama") or "not found (fine if the server runs elsewhere)", False))

    # 6. Optional: Claude
    has_sdk = importlib.util.find_spec("anthropic") is not None
    rows.append((OK if has_sdk else WARN, "anthropic SDK (optional)",
                 "installed" if has_sdk else "pip install anthropic  (only for Claude)", False))
    rows.append((OK if claude_credentials_present() else WARN, "Claude credentials (optional)",
                 "found" if claude_credentials_present() else "ANTHROPIC_API_KEY not set - local-only mode",
                 False))
    if cfg.searxng_url:
        try:
            _get_json(cfg.searxng_url.rstrip("/") + "/search?q=test&format=json")
            rows.append((OK, "SearXNG (optional)", cfg.searxng_url, False))
        except Exception as e:
            rows.append((WARN, "SearXNG (optional)", str(e), False))
    return rows


def main(cfg: Config) -> int:
    rows = run_checks(cfg)
    print("\nHybrid agent - readiness check\n")
    for status, name, detail, mandatory in rows:
        tag = "required" if mandatory else "optional"
        print(f"  [{status}] {name:<34} ({tag})  {detail}")
    failed = [r for r in rows if r[3] and r[0] == FAIL]
    print()
    if failed:
        print("Not ready for key-free use. Fix the FAIL rows above (see docs/LOCAL_MODEL_SETUP.md).")
        return 1
    print("Ready: the agent can run with no API key.")
    return 0
