"""[TOOLS] The tool suite.

    build_full_registry(ctx)          every built-in tool
    build_registry(ctx, profile)      a profile's selection (see profiles.py)
"""
from __future__ import annotations

from ..core.errors import ToolError
from .builtin import ALL_MODULES
from .profiles import PROFILES, apply_profile
from .registry import S, Tool, ToolContext, ToolRegistry, ToolResult

__all__ = ["PROFILES", "S", "Tool", "ToolContext", "ToolError", "ToolRegistry", "ToolResult",
           "build_full_registry", "build_registry"]


def build_full_registry(ctx: ToolContext) -> ToolRegistry:
    reg = ToolRegistry(ctx)
    for module in ALL_MODULES:
        module.register(reg)
    return reg


def build_registry(ctx: ToolContext, profile: str = "core", include_delegate: bool = False) -> ToolRegistry:
    """Registry for one agent.

    `delegate_to_local` only makes sense when Claude is the main brain (the
    local model is then a cheaper helper), so it's dropped unless asked for.
    """
    reg = apply_profile(build_full_registry(ctx), profile)
    if not include_delegate:
        reg.unregister("delegate_to_local")
    elif "delegate_to_local" not in reg:
        reg.register(build_full_registry(ctx)["delegate_to_local"])
    return reg
