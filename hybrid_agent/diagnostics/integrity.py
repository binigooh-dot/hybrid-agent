"""[DIAGNOSTICS / integrity] Static self-checks of the installed code.

Fast checks that need no model and no network:
  * every module compiles
  * every tool's schema matches its function signature, and every tool is labelled
  * every profile references real tools; every council role references a real profile
  * the persona presets load and render faces (when the personas package exists)
"""
from __future__ import annotations

import compileall
import io
from contextlib import redirect_stdout
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent


def check_compile() -> tuple[bool, str]:
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


def check_personas() -> tuple[bool, str]:
    try:
        from ..personas import load_presets
        from ..personas.faces import EXPRESSIONS, render_face
    except ImportError:
        return True, "personas package not installed (skipped)"
    presets = load_presets()
    for p in presets:
        for ex in EXPRESSIONS:
            svg = render_face(p.face, ex)
            if not svg.startswith("<svg"):
                return False, f"{p.id}: face '{ex}' did not render"
    return True, f"{len(presets)} personas x {len(EXPRESSIONS)} expressions render"


CHECKS = [("compile", check_compile), ("tools", check_tools),
          ("profiles+roles", check_profiles_and_roles), ("personas", check_personas)]
