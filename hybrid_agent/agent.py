"""The agent loop.

    user message
        |
        v
    +-> model.chat(system, history, tools) --> no tool calls? --> return answer
    |                |
    |           tool calls
    |                v
    +--- run each tool, append results to history

Analogy: a chef (the model) reading a recipe. Each step they either ask a
kitchen hand (a tool) to fetch/chop/measure something, or they plate the dish
(the final answer). `max_steps` stops a chef who keeps asking forever.
"""
from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import Callable

from .backends.base import Backend
from .messages import Message
from .tools.registry import ToolRegistry

DEFAULT_SYSTEM_PROMPT = """\
You are a capable autonomous assistant working inside a sandboxed workspace
directory on the user's computer ({os}). Use the tools to inspect files, run
code, search the web and remember things, rather than guessing.

Guidelines:
- For multi-step tasks, write a short plan with update_plan and keep it current.
- Read a file before editing it. Prefer edit_file for small changes.
- Use calculator for arithmetic.
- Save durable facts the user tells you (preferences, project details) with remember;
  check recall when they might be relevant.
- If a tool returns an error, read it, fix the arguments, and try again.
- When finished, reply with a concise final answer and no tool calls.
"""

EventHook = Callable[[str, dict], None]


class Agent:
    def __init__(self, backend: Backend, tools: ToolRegistry, system_prompt: str | None = None,
                 max_steps: int = 25, log_dir: Path | None = None,
                 on_event: EventHook | None = None):
        self.backend = backend
        self.tools = tools
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT.format(os=platform.system())
        self.max_steps = max_steps
        self.messages: list[Message] = []
        self.on_event = on_event or (lambda kind, data: None)
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self._log_path: Path | None = None
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            self._log_path = log_dir / f"session-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"

    # ------------------------------------------------------------------
    def reset(self) -> None:
        self.messages.clear()

    def _log(self, kind: str, **data) -> None:
        self.on_event(kind, data)
        if self._log_path:
            with self._log_path.open("a") as f:
                f.write(json.dumps({"t": time.time(), "kind": kind, **data}, default=str) + "\n")

    def _append(self, msg: Message) -> None:
        self.messages.append(msg)
        self._log("message", message=msg.to_dict())

    # ------------------------------------------------------------------
    def run(self, user_input: str) -> str:
        """Process one user message to completion and return the final text."""
        self._append(Message(role="user", content=user_input))
        specs = self.tools.specs()

        for step in range(1, self.max_steps + 1):
            resp = self.backend.chat(self.system_prompt, self.messages, specs)
            for k in self.usage:
                self.usage[k] += resp.usage.get(k, 0)
            self._log("model", step=step, provider=resp.provider, model=resp.model,
                      stop_reason=resp.stop_reason, usage=resp.usage)
            msg = resp.message
            self._append(msg)

            if not msg.tool_calls:
                if resp.stop_reason == "max_tokens":
                    return msg.content + "\n\n[stopped: the model hit its output limit]"
                return msg.content

            if msg.content:
                self._log("thought", text=msg.content)
            for call in msg.tool_calls:
                self._log("tool_call", name=call.name, arguments=call.arguments)
                result = self.tools.execute(call)
                self._log("tool_result", name=call.name, is_error=result.is_error,
                          preview=result.content[:500])
                self._append(Message(role="tool", content=result.content, tool_call_id=call.id,
                                     name=call.name, is_error=result.is_error))

        return f"[stopped after {self.max_steps} steps without a final answer]"
