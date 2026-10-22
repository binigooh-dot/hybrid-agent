"""[CLI / doctor] `python -m hybrid_agent doctor` - checks everything needed to run.

Separates MANDATORY checks (needed to run with no API key) from OPTIONAL ones
(Claude). Exit code 0 means the agent can run key-free.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import urllib.request

from ..core.config import Config, claude_credentials_present

OK, WARN, FAIL = "PASS", "WARN", "FAIL"


def _get_json(url: str, timeout: float = 3.0):
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"not an http(s) URL: {url}")
    # Reviewed (B310): scheme checked above
    with urllib.request.urlopen(url, timeout=timeout) as r:  # nosec B310
        return json.loads(r.read().decode())


def model_available(want: str, models: list[str]) -> bool:
    """Ollama resolves a tag-less name to ':latest', so 'qwen2.5' only matches
    'qwen2.5:latest' - NOT 'qwen2.5:14b' (that was a bug in v0.1)."""
    return want in models or (":" not in want and f"{want}:latest" in models)


Row = tuple[str, str, str, bool]  # (status, check, detail, required)


def check_python(cfg: Config) -> list[Row]:
    ok = sys.version_info >= (3, 10)
    return [(OK if ok else FAIL, "Python >= 3.10", sys.version.split()[0], True)]


def check_local_model(cfg: Config) -> list[Row]:
    """Server reachable, then the configured model is pulled."""
    server = f"Local server ({cfg.local_provider})"
    model = f"Local model '{cfg.local_model}'"
    try:
        if cfg.local_provider == "ollama":
            models = [m["name"] for m in _get_json(cfg.local_base_url.rstrip("/") + "/api/tags").get("models", [])]
        else:
            models = [m["id"] for m in _get_json(cfg.local_base_url.rstrip("/") + "/v1/models").get("data", [])]
    except Exception as e:  # noqa: BLE001 - deliberate boundary: report the failure, never crash
        from ..core.home import home_dir
        hint = (" - press Set up now in the app (or Settings > Model engine > Start)" if home_dir()
                else " - install Ollama and run `ollama serve`") if cfg.local_provider == "ollama" else ""
        return [(FAIL, server, f"{cfg.local_base_url}: {e}{hint}", True), (FAIL, model, "skipped (server down)", True)]
    have = model_available(cfg.local_model, models)
    detail = "available" if have else \
        f"not downloaded yet - press Set up now in the app, or run `ollama pull {cfg.local_model}` " \
        f"(have: {', '.join(models) or 'none'})"
    return [(OK, server, cfg.local_base_url, True), (OK if have else FAIL, model, detail, True)]


def check_workspace(cfg: Config) -> list[Row]:
    from ..security.guards import validate_workspace
    try:
        path = validate_workspace(cfg.workspace)
    except ValueError as e:
        return [(FAIL, "Workspace location safe", str(e), True)]
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return [(FAIL, "Workspace writable", str(e), True)]
    return [(OK, "Workspace safe + writable", str(path), True)]


def check_optional_tools(cfg: Config) -> list[Row]:
    rows: list[Row] = []
    if cfg.local_provider == "ollama":
        rows.append((OK if shutil.which("ollama") else WARN, "`ollama` CLI on PATH",
                     shutil.which("ollama") or "not found (fine if the server runs elsewhere)", False))
    has_sdk = importlib.util.find_spec("anthropic") is not None
    rows.append((OK if has_sdk else WARN, "anthropic SDK (optional)",
                 "installed" if has_sdk else "pip install anthropic  (only for Claude)", False))
    has_key = claude_credentials_present()
    rows.append((OK if has_key else WARN, "Claude credentials (optional)",
                 "found" if has_key else "ANTHROPIC_API_KEY not set - local-only mode", False))
    return rows


def check_agents_and_council(cfg: Config) -> list[Row]:
    from ..agents import load_agents
    agents = load_agents(cfg.agents_dir)
    rows: list[Row] = [(OK, "Agents (optional)", f"{len(agents)}: {', '.join(agents)}", False)]
    if cfg.council_config:
        try:
            from ..council import MemberSpec
            data = json.loads(cfg.council_config.read_text(encoding="utf-8"))
            specs = [MemberSpec.from_dict(m) for m in data.get("members", [])]
            n = len(specs) + len(data.get("agents", []))
            rows.append((OK, "Council config (optional)", f"{cfg.council_config}: {n} members", False))
        except Exception as e:  # noqa: BLE001 - deliberate boundary: report the failure, never crash
            rows.append((WARN, "Council config (optional)", f"{cfg.council_config}: {e}", False))
    return rows


def check_search(cfg: Config) -> list[Row]:
    if not cfg.searxng_url:
        return []
    try:
        _get_json(cfg.searxng_url.rstrip("/") + "/search?q=test&format=json")
        return [(OK, "SearXNG (optional)", cfg.searxng_url, False)]
    except Exception as e:  # noqa: BLE001 - deliberate boundary: report the failure, never crash
        return [(WARN, "SearXNG (optional)", str(e), False)]


CHECKS = [check_python, check_local_model, check_workspace, check_optional_tools,
          check_agents_and_council, check_search]


def run_checks(cfg: Config) -> list[Row]:
    """Every check, in order. Each returns rows of (status, check, detail, required)."""
    return [row for check in CHECKS for row in check(cfg)]


def main(cfg: Config) -> int:
    rows = run_checks(cfg)
    print("\nHybrid agent - readiness check\n")
    for status, name, detail, mandatory in rows:
        tag = "required" if mandatory else "optional"
        print(f"  [{status}] {name:<34} ({tag})  {detail}")
    failed = [r for r in rows if r[3] and r[0] == FAIL]
    print()
    if failed:
        print("Not ready for key-free use. Fix the FAIL rows above (see docs/02_LOCAL_MODEL_SETUP.md).")
        return 1
    print("Ready: the agent can run with no API key.")
    return 0
