"""The tool suite. `build_default_registry` wires every built-in tool."""
from __future__ import annotations

from . import execution, filesystem, memory, utilities, web
from .registry import Tool, ToolContext, ToolError, ToolRegistry, ToolResult

__all__ = ["Tool", "ToolContext", "ToolError", "ToolRegistry", "ToolResult", "build_default_registry"]


def build_default_registry(ctx: ToolContext, include_delegate: bool = False) -> ToolRegistry:
    """Register all built-in tools.

    `delegate_to_local` is only useful when the main brain is Claude (so the
    local model is a cheaper helper); it's left out when the local model is
    already the main brain.
    """
    reg = ToolRegistry(ctx)
    for module in (filesystem, execution, web, memory, utilities):
        module.register(reg)
    if not include_delegate:
        reg._tools.pop("delegate_to_local", None)
    return reg
