"""[DIAGNOSTICS / integrity] Static self-checks of the installed code.

Fast checks that need no model and no network:
  * every module compiles
  * every tool's schema matches its function signature, and every tool is labelled
  * every profile references real tools; every council role references a real profile
  * the built-in agents' face frames are well-formed ASCII
  * the release manifest (if present) matches the installed files
"""
from __future__ import annotations

import compileall
import io
from contextlib import redirect_stdout
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent


def check_compile() -> tuple[bool, str]:
    import sys
    if getattr(sys, "frozen", False):
        return True, "packaged app: code was compiled at build time (the manifest check covers integrity)"
    buf = io.StringIO()
    with redirect_stdout(buf):
        ok = compileall.compile_dir(str(PKG), quiet=1, force=False)
    return bool(ok), "all modules compile" if ok else buf.getvalue()[-500:]


def check_tools() -> tuple[bool, str]:
    from ..tools import ToolContext, build_full_registry
    from ..tools.registry import RISK_LEVELS, check_signature
    reg = build_full_registry(ToolContext(workspace=Path(".")))
    problems = [p for t in reg.tools() for p in check_signature(t)]
    problems += [f"{n}: bad label" for n in reg.names()
                 if reg[n].risk not in RISK_LEVELS or reg[n].category == "misc"]
    return not problems, f"{len(reg)} tools consistent" if not problems else "; ".join(problems[:5])


def check_profiles_and_roles() -> tuple[bool, str]:
    from ..council.roles import ROLES
    from ..tools import PROFILES, ToolContext, build_full_registry, build_registry
    full = build_full_registry(ToolContext(workspace=Path(".")))
    problems = [f"profile {p}: unknown tool {t}" for p, spec in PROFILES.items()
                for t in spec.get("names", []) if t not in full]
    for role in ROLES.values():
        try:
            build_registry(ToolContext(workspace=Path(".")), role.tools)
        except ValueError as e:
            problems.append(f"role {role.key}: {e}")
    return not problems, f"{len(PROFILES)} profiles, {len(ROLES)} roles valid" if not problems else "; ".join(problems)


def check_agents() -> tuple[bool, str]:
    from ..agents import builtin_agents, render_all
    agents = builtin_agents()
    for a in agents.values():
        for ex, frames in render_all(a.face).items():
            for frame in frames:
                rows = frame.split("\n")
                if len(rows) != 7 or any(len(r) != 16 for r in rows) or not all(32 <= ord(c) < 127 for c in frame.replace("\n", "")):
                    return False, f"{a.id}: face '{ex}' is malformed"
    return True, f"{len(agents)} built-in agents: every face frame is 7x16 plain ASCII"


def check_manifest() -> tuple[bool, str]:
    from ..security.audit import verify_manifest
    status, detail = verify_manifest()
    if status == "changed" and (PKG.parent / ".git").exists():
        return True, f"development checkout differs from last release build: {detail}"
    return status != "changed", detail


CHECKS = [("compile", check_compile), ("tools", check_tools), ("profiles+roles", check_profiles_and_roles),
          ("agents", check_agents), ("manifest", check_manifest)]
