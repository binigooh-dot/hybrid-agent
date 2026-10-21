"""[TOOLS] The tool suite.

    build_full_registry(ctx)          every built-in tool
    build_registry(ctx, profile)      a profile's selection (see profiles.py)
"""
from __future__ import annotations

import functools
from pathlib import Path

from ..core.errors import ToolError
from .builtin import ALL_MODULES
from .profiles import PROFILES, apply_profile
from .registry import S, Tool, ToolContext, ToolRegistry, ToolResult

__all__ = ["PROFILES", "S", "Tool", "ToolContext", "ToolError", "ToolRegistry", "ToolResult",
           "build_full_registry", "build_registry"]


@functools.lru_cache(maxsize=1)
def _catalog() -> tuple[Tool, ...]:
    """Every built-in tool, defined once. Tool functions receive their context
    as an argument, so the same definitions are shared by every registry."""
    reg = ToolRegistry(ToolContext(workspace=Path(".")))
    for module in ALL_MODULES:
        module.register(reg)
    return tuple(reg.tools())


def build_full_registry(ctx: ToolContext) -> ToolRegistry:
    reg = ToolRegistry(ctx)
    reg._tools = {t.name: t for t in _catalog()}
    return reg


def build_registry(ctx: ToolContext, profile: str = "core", include_delegate: bool = False,
                   safe_mode: bool = False) -> ToolRegistry:
    """Registry for one agent.

    `delegate_to_local` only makes sense when Claude is the main brain (the
    local model is then a cheaper helper), so it's dropped unless asked for.
    safe_mode removes every tool that can write or execute (read-only agent).
    """
    reg = apply_profile(build_full_registry(ctx), profile)
    if safe_mode:
        reg = reg.subset(max_risk="network")
    if not include_delegate:
        reg.unregister("delegate_to_local")
    elif "delegate_to_local" not in reg:
        reg.register(build_full_registry(ctx)["delegate_to_local"])
    return reg
