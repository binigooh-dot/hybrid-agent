"""[CORE / agent] The agent loop.

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
import re
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from ..backends.base import Backend
from ..security.redact import redact_obj
from ..tools.registry import ToolRegistry
from .errors import AgentCancelled
from .messages import Message

DEFAULT_SYSTEM_PROMPT = """\
You are a capable autonomous assistant working inside a sandboxed workspace
directory on the user's computer ({os}). Use the tools to inspect files, run
code, search the web and remember things, rather than guessing.

Guidelines:
- For multi-step tasks, write a short plan with update_plan and keep it current.
- Read a file before editing it. Prefer edit_file for small changes.
- Use calculator / statistics / unit_convert for numbers instead of mental maths.
- Save durable facts the user tells you (preferences, project details) with remember;
  check recall when they might be relevant.
- If a tool returns an error, read it, fix the arguments, and try again.
- When finished, reply with a concise final answer and no tool calls.
"""

EventHook = Callable[[str, dict], None]

TRUNCATED_CALL = ("Your previous reply hit the output-length limit, so this tool call's "
                  "arguments were cut off and it was NOT run. Retry with smaller input "
                  "(e.g. write a large file in several edit/append steps).")
REPEATED_CALL = ("This exact tool call (same tool, same arguments) has already been made {n} times "
                 "in a row and was NOT run again. The result will not change - use the earlier "
                 "result, change the arguments, or try a different approach.")
MAX_IDENTICAL_CALLS = 3
KEEP_RECENT_TOOL_RESULTS = 4       # never trimmed
TRIMMED_PREFIX = "[older tool output shortened to save context; first 400 chars] "


class Agent:
    def __init__(self, backend: Backend, tools: ToolRegistry, system_prompt: str | None = None,
                 max_steps: int = 25, log_dir: Path | None = None,
                 on_event: EventHook | None = None, name: str = "agent", context_chars: int | None = None):
        self.name = name
        self.backend = backend
        self.tools = tools
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT.format(os=platform.system())
        self.max_steps = max_steps
        # Approximate history budget in characters (~4 chars per token). When the
        # conversation outgrows it, old tool outputs are shortened (local models only).
        self.context_chars = context_chars
        self.messages: list[Message] = []
        self.on_event = on_event or (lambda kind, data: None)
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self._cancel = threading.Event()
        self._log_path: Path | None = None
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            # name + random suffix: several agents (a council) may start in the same second
            safe = re.sub(r"[^\w.-]", "_", name)
            self._log_path = log_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}-{uuid.uuid4().hex[:6]}.jsonl"

    # ------------------------------------------------------------------
    def reset(self) -> None:
        self.messages.clear()

    def cancel(self) -> None:
        """Ask a running run() to stop at the next safe point (thread-safe)."""
        self._cancel.set()

    def _trim_history(self) -> None:
        """Keep a local model's context from overflowing: shorten the oldest tool
        results first, always keeping the most recent ones whole.

        Analogy: clearing old papers off a small desk so today's work still fits.
        """
        if not self.context_chars or not self.backend.allows_history_trim:
            return
        total = len(self.system_prompt) + sum(len(m.content) for m in self.messages)
        if total <= self.context_chars:
            return
        tool_idx = [i for i, m in enumerate(self.messages) if m.role == "tool"]
        saved = 0
        for i in tool_idx[:-KEEP_RECENT_TOOL_RESULTS]:
            m = self.messages[i]
            if m.content.startswith(TRIMMED_PREFIX) or len(m.content) <= 600:
                continue
            before = len(m.content)
            m.content = TRIMMED_PREFIX + m.content[:400]
            saved += before - len(m.content)
            if total - saved <= self.context_chars:
                break
        if saved:
            self._log("trimmed", chars_saved=saved, budget=self.context_chars)

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise AgentCancelled("stopped by user")

    def _log(self, kind: str, **data) -> None:
        data = redact_obj(data)  # secrets never reach the log file or the GUI
        self.on_event(kind, {"agent": self.name, **data})
        if self._log_path:
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "agent": self.name, "kind": kind, **data},
                                   default=str) + "\n")

    def _append(self, msg: Message) -> None:
        self.messages.append(msg)
        self._log("message", message=msg.to_dict())

    # ------------------------------------------------------------------
    def run(self, user_input: str) -> str:
        """Process one user message to completion and return the final text.

        If the model backend fails part-way, the conversation is rolled back
        to how it was before this call, so a retry starts clean (no orphaned
        user message or unanswered tool calls in the history).
        """
        checkpoint = len(self.messages)
        self._cancel.clear()
        try:
            return self._run(user_input)
        except BaseException:
            del self.messages[checkpoint:]
            raise

    def _run(self, user_input: str) -> str:
        self._append(Message(role="user", content=user_input))
        specs = self.tools.specs()
        last_sig, streak = None, 0

        for step in range(1, self.max_steps + 1):
            self._check_cancel()
            self._trim_history()
            resp = self.backend.chat(self.system_prompt, self.messages, specs)
            self._check_cancel()
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
            truncated = resp.stop_reason == "max_tokens"
            for call in msg.tool_calls:
                self._check_cancel()
                sig = (call.name, json.dumps(call.arguments, sort_keys=True, default=str))
                streak = streak + 1 if sig == last_sig else 1
                last_sig = sig
                if truncated:
                    # Every tool call still needs a result (Claude requires it),
                    # but never run one whose arguments may be cut off.
                    content, is_error = TRUNCATED_CALL, True
                elif streak > MAX_IDENTICAL_CALLS:
                    # Loop guard: small models sometimes repeat one call forever.
                    content, is_error = REPEATED_CALL.format(n=streak - 1), True
                else:
                    self._log("tool_call", name=call.name, arguments=call.arguments)
                    result = self.tools.execute(call)
                    content, is_error = result.content, result.is_error
                self._log("tool_result", name=call.name, is_error=is_error, preview=content[:500])
                self._append(Message(role="tool", content=content, tool_call_id=call.id,
                                     name=call.name, is_error=is_error))

        return f"[stopped after {self.max_steps} steps without a final answer]"
