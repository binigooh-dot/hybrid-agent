"""[TOOLS / framework] Tool registry: how tools are declared, described, filtered and run.

Analogy: the registry is a restaurant menu. Each Tool is a dish with a name,
a description, and a list of required ingredients (the JSON schema). The
model "orders" by name with arguments; the registry checks the order is
valid, sends it to the kitchen (the Python function), and returns the plate
(a ToolResult) - including a polite error if the order was malformed.

Every tool carries two labels:
  category - what area it belongs to ("files", "web", "code", ...)
  risk     - what it can affect, ordered:
               read    - only looks at things
               network - contacts other machines (internet / LAN)
               write   - changes files in the workspace
               execute - runs arbitrary code / commands
Profiles (tools/profiles.py) and council members use these labels to pick
which tools an agent gets.
"""
from __future__ import annotations

import inspect
import json
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.errors import ToolError
from ..core.messages import ToolCall

# approver(tool_name, arguments, reason) -> True to allow
Approver = Callable[[str, dict, str], bool]
# ask_user(question) -> answer text
AskUser = Callable[[str], str]

RISK_LEVELS = ("read", "network", "write", "execute")


def _deny(name: str, args: dict, reason: str) -> bool:
    return False


def _no_user(question: str) -> str:
    return "(No user is available to answer. Make a reasonable assumption and state it.)"


@dataclass
class ToolContext:
    """Shared state handed to every tool call."""
    workspace: Path
    approver: Approver = _deny
    ask_user: AskUser = _no_user
    max_output: int = 20000
    shell_timeout: int = 60
    searxng_url: str | None = None
    allow_private_network: bool = False                  # web tools may reach LAN/loopback (see core/netguard.py)
    agent_name: str = "agent"                             # who is calling (council members differ)
    state: dict[str, Any] = field(default_factory=dict)   # per-agent scratch (plan, ...)
    local_backend: Any = None                             # for delegate_to_local
    blackboard: Any = None                                # council.Blackboard, shared by members


@dataclass
class ToolResult:
    content: str
    is_error: bool = False


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]
    category: str = "misc"
    risk: str = "read"
    requires_approval: bool = False

    def __post_init__(self):
        if self.risk not in RISK_LEVELS:
            raise ValueError(f"tool {self.name}: risk must be one of {RISK_LEVELS}")

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


# --------------------------------------------------------------------- schema
def S(**fields: str | dict) -> dict[str, Any]:
    """Compact JSON-schema builder used by all built-in tools.

        S(path="string|File path", limit="integer?|Max lines")

    "type|description"; a trailing "?" on the type marks the field optional.
    Pass a dict for anything fancier; add "optional": True to it to make it
    optional.
    """
    props: dict[str, Any] = {}
    required: list[str] = []
    for name, given in fields.items():
        if isinstance(given, dict):
            spec = dict(given)
            optional = spec.pop("optional", False)
        else:
            typ, _, desc = given.partition("|")
            optional = typ.endswith("?")
            spec = {"type": typ.rstrip("?")}
            if desc:
                spec["description"] = desc
        props[name] = spec
        if not optional:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> list[str]:
    """Minimal JSON-schema check (required keys, unknown keys, top-level types, enums).

    Local models make more argument mistakes than Claude, so a clear error
    message here lets them self-correct on the next step.
    """
    if not isinstance(args, dict):
        return ["arguments must be a JSON object"]
    errors = []
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in args:
            errors.append(f"missing required argument '{key}'")
    for key, value in args.items():
        if key not in props:
            errors.append(f"unknown argument '{key}' (valid: {', '.join(props) or 'none'})")
            continue
        p = props[key]
        t = p.get("type")
        if t in _TYPE_CHECKS and not _TYPE_CHECKS[t](value):
            if not (t == "number" and isinstance(value, int)):
                errors.append(f"argument '{key}' should be {t}, got {type(value).__name__}")
        if "enum" in p and value not in p["enum"]:
            errors.append(f"argument '{key}' must be one of {p['enum']}")
    return errors


# ------------------------------------------------------------------- registry
class ToolRegistry:
    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self._tools: dict[str, Tool] = {}

    # -- building
    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def tool(self, name: str, description: str, parameters: dict[str, Any], *,
             category: str = "misc", risk: str = "read", requires_approval: bool = False):
        """Decorator form:

            @registry.tool("echo", "Echo text back", S(text="string"), category="text")
            def echo(ctx, text): return text
        """
        def wrap(fn):
            self.register(Tool(name, description, parameters, fn, category, risk, requires_approval))
            return fn
        return wrap

    def group(self, category: str, **defaults):
        """Decorator factory for a module's tools, so each @tool needn't repeat its labels:

            t = registry.group("web", risk="network")
            @t("fetch_url", "...", S(url="string"))
            def fetch_url(ctx, url): ...
        """
        def decorator(name: str, description: str, parameters: dict[str, Any], **kw):
            return self.tool(name, description, parameters, category=category, **{**defaults, **kw})
        return decorator

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    # -- querying
    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __getitem__(self, name: str) -> Tool:
        return self._tools[name]

    def tools(self) -> list[Tool]:
        """All tools, sorted by name."""
        return [self._tools[n] for n in self.names()]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def categories(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for n in self.names():
            out.setdefault(self._tools[n].category, []).append(n)
        return dict(sorted(out.items()))

    def specs(self) -> list[dict[str, Any]]:
        # Sorted so the tool list is byte-identical every request (helps
        # Claude's prompt cache).
        return [self._tools[n].spec() for n in self.names()]

    def subset(self, *, names: list[str] | None = None, categories: list[str] | None = None,
               max_risk: str | None = None, exclude: list[str] | None = None,
               ctx: ToolContext | None = None) -> "ToolRegistry":
        """A new registry with a filtered selection of these tools.

        A tool is kept if it matches `names` OR `categories` (when neither is
        given, all tools match), its risk is <= max_risk, and it isn't excluded.
        `ctx` lets the subset run with a different context (council members).
        """
        out = ToolRegistry(ctx or self.ctx)
        limit = RISK_LEVELS.index(max_risk) if max_risk else len(RISK_LEVELS)
        for t in self._tools.values():
            picked = (names is None and categories is None) \
                or (names is not None and t.name in names) \
                or (categories is not None and t.category in categories)
            if picked and RISK_LEVELS.index(t.risk) <= limit and t.name not in (exclude or []):
                out._tools[t.name] = t
        return out

    # -- running
    def execute(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(f"Unknown tool '{call.name}'. Available: {', '.join(self.names())}",
                              is_error=True)
        errors = validate_args(tool.parameters, call.arguments)
        if errors:
            return ToolResult("Invalid arguments: " + "; ".join(errors), is_error=True)
        if tool.requires_approval and not self.ctx.approver(tool.name, call.arguments, f"{tool.risk} tool"):
            return ToolResult("The user declined to run this tool call.", is_error=True)
        try:
            out = tool.func(self.ctx, **call.arguments)
        except ToolError as e:
            return ToolResult(str(e), is_error=True)
        except Exception as e:  # noqa: BLE001 - deliberate boundary: report the failure, never crash
            tb = traceback.format_exc(limit=3)
            return ToolResult(f"{type(e).__name__}: {e}\n{tb}", is_error=True)
        text = out if isinstance(out, str) else json.dumps(out, indent=2, default=str)
        if len(text) > self.ctx.max_output:
            text = (text[: self.ctx.max_output]
                    + f"\n...[truncated {len(text) - self.ctx.max_output} chars]")
        return ToolResult(text)


# A process-wide lock for tools that touch shared files (memory, document index)
# so several council members can run in parallel threads safely.
FILE_LOCK = threading.RLock()


def check_signature(tool: Tool) -> list[str]:
    """Dev helper (used by tests): schema properties must match the function's
    keyword parameters, so the model can never be told about an argument the
    function doesn't accept."""
    params = list(inspect.signature(tool.func).parameters)[1:]  # skip ctx
    props = list(tool.parameters.get("properties", {}))
    problems = [f"{tool.name}: schema has '{p}' but function doesn't" for p in props if p not in params]
    problems += [f"{tool.name}: function has '{p}' but schema doesn't" for p in params if p not in props]
    return problems
