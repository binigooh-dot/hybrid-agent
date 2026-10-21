"""Tool registry: how tools are declared, described to the model, and run.

Analogy: the registry is a restaurant menu. Each Tool is a dish with a name,
a description, and a list of required ingredients (the JSON schema). The
model "orders" by name with arguments; the registry checks the order is
valid, sends it to the kitchen (the Python function), and returns the plate
(a ToolResult) - including a polite error if the order was malformed.
"""
from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..messages import ToolCall

# approver(tool_name, arguments, reason) -> True to allow
Approver = Callable[[str, dict, str], bool]


@dataclass
class ToolContext:
    """Shared state handed to every tool."""
    workspace: Path
    approver: Approver = lambda name, args, reason: False
    max_output: int = 20000
    shell_timeout: int = 60
    searxng_url: str | None = None
    state: dict[str, Any] = field(default_factory=dict)  # scratch space (e.g. todo list)
    local_backend: Any = None                             # for delegate_to_local


@dataclass
class ToolResult:
    content: str
    is_error: bool = False


class ToolError(Exception):
    """Raise inside a tool for an expected failure; message goes to the model."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]
    requires_approval: bool = False

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> list[str]:
    """Minimal JSON-schema check (required keys, top-level types, enums).

    Local models make more argument mistakes than Claude, so a clear error
    message here lets them self-correct on the next step.
    """
    errors = []
    if not isinstance(args, dict):
        return ["arguments must be a JSON object"]
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in args:
            errors.append(f"missing required argument '{key}'")
    for key, value in args.items():
        if key not in props:
            if schema.get("additionalProperties") is False:
                errors.append(f"unknown argument '{key}'")
            continue
        p = props[key]
        t = p.get("type")
        if t and t in _TYPE_CHECKS and not _TYPE_CHECKS[t](value):
            errors.append(f"argument '{key}' should be {t}, got {type(value).__name__}")
        if "enum" in p and value not in p["enum"]:
            errors.append(f"argument '{key}' must be one of {p['enum']}")
    return errors


class ToolRegistry:
    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def tool(self, name: str, description: str, parameters: dict[str, Any],
             requires_approval: bool = False):
        """Decorator form:

            @registry.tool("echo", "Echo text back", {...schema...})
            def echo(ctx, text): return text
        """
        def wrap(fn):
            self.register(Tool(name, description, parameters, fn, requires_approval))
            return fn
        return wrap

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[dict[str, Any]]:
        # Sorted so the tool list is byte-identical every request (helps
        # Claude's prompt cache).
        return [self._tools[n].spec() for n in self.names()]

    def execute(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(f"Unknown tool '{call.name}'. Available: {', '.join(self.names())}",
                              is_error=True)
        errors = validate_args(tool.parameters, call.arguments)
        if errors:
            return ToolResult("Invalid arguments: " + "; ".join(errors), is_error=True)
        if tool.requires_approval and not self.ctx.approver(tool.name, call.arguments, "requires approval"):
            return ToolResult("The user declined to run this tool call.", is_error=True)
        try:
            out = tool.func(self.ctx, **call.arguments)
        except ToolError as e:
            return ToolResult(str(e), is_error=True)
        except Exception as e:  # never let a tool crash the agent
            tb = traceback.format_exc(limit=3)
            return ToolResult(f"{type(e).__name__}: {e}\n{tb}", is_error=True)
        text = out if isinstance(out, str) else json.dumps(out, indent=2, default=str)
        if len(text) > self.ctx.max_output:
            text = (text[: self.ctx.max_output]
                    + f"\n...[truncated {len(text) - self.ctx.max_output} chars]")
        return ToolResult(text)
