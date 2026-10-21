"""Scripted backend: returns pre-written replies. No model, no network.

Used by the test-suite and for a smoke-test demo (`--backend scripted`) so you
can verify the agent loop + tools work before installing any model.
"""
from __future__ import annotations

from typing import Callable

from ..messages import LLMResponse, Message, ToolCall
from .base import Backend

Step = Message | Callable[[list[Message]], Message]


class ScriptedBackend(Backend):
    name = "scripted"
    model = "scripted"

    def __init__(self, steps: list[Step]):
        self.steps = list(steps)
        self.calls: list[list[Message]] = []   # what the agent sent, for assertions

    def chat(self, system, messages, tools=None) -> LLMResponse:
        self.calls.append(list(messages))
        if not self.steps:
            msg = Message(role="assistant", content="(script finished)")
        else:
            step = self.steps.pop(0)
            msg = step(messages) if callable(step) else step
        stop = "tool_use" if msg.tool_calls else "end_turn"
        return LLMResponse(message=msg, stop_reason=stop, provider=self.name, model=self.model)


def demo_script() -> ScriptedBackend:
    """A tiny canned conversation that exercises three tools."""
    return ScriptedBackend([
        Message(role="assistant", content="Let me check the time and do some maths.",
                tool_calls=[ToolCall("c1", "current_time", {}),
                            ToolCall("c2", "calculator", {"expression": "2**10 + 7"})]),
        Message(role="assistant", content="Saving a note.",
                tool_calls=[ToolCall("c3", "write_file",
                                     {"path": "demo.txt", "content": "hello from the scripted demo\n"})]),
        lambda msgs: Message(role="assistant", content=(
            "Demo complete. Tool results were:\n"
            + "\n".join(f"- {m.name}: {m.content[:80]}" for m in msgs if m.role == "tool"))),
    ])
