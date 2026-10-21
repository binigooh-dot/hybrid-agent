"""[BACKENDS / scripted] Scripted backend: returns pre-written replies. No model, no network.

Used by the test-suite and for a smoke-test demo (`--backend scripted`) so you
can verify the agent loop + tools work before installing any model.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from ..core.messages import LLMResponse, Message, ToolCall
from .base import Backend

Step = Message | Callable[[list[Message]], Message]


class ScriptedBackend(Backend):
    name = "scripted"
    model = "scripted"
    allows_history_trim = True

    def __init__(self, steps: Sequence[Step]):
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


class CannedBackend(Backend):
    allows_history_trim = True

    """Deterministic, prompt-aware fake model for council demos and tests.

    It writes the kind of reply the council protocols ask for: posts one note
    to the shared board (to exercise tool use), proposes options when asked,
    and ends opinions with VOTE/CONFIDENCE lines, picking an option based on
    the member's name so the demo shows some disagreement.
    """
    name = "canned"
    model = "canned"

    def __init__(self, member: str = "agent"):
        self.member = member

    def chat(self, system, messages, tools=None) -> LLMResponse:
        last = messages[-1]
        tool_names = {t["name"] for t in tools or []}
        if last.role == "user" and "board_post" in tool_names and "Council question" in last.content \
                and not any(m.role == "tool" for m in messages):
            msg = Message(role="assistant", content="Sharing a note first.", tool_calls=[ToolCall(
                f"c-{self.member}", "board_post",
                {"content": f"{self.member} is looking into this.", "topic": "status"})])
            return LLMResponse(msg, "tool_use", self.name, self.model)
        prompt = next(m.content for m in reversed(messages) if m.role == "user")
        if "List 2 to 5 distinct options" in prompt:
            text = "- Option A\n- Option B"
        elif "As chair" in prompt:
            text = (f"[{self.member}] Council decision (demo): the members' views were weighed; "
                    "see the vote result above. Confidence: medium.")
        else:
            options = re.findall(r"^- (.+)$", prompt.split("Options:", 1)[1], re.M) if "Options:" in prompt else []
            topic = re.search(r"Council (?:question|task):\n(.+)", prompt)
            kind = "revised draft" if "Revise the draft" in prompt else "critique" if "Critique it" in prompt \
                else "position"
            text = f"[{self.member}] My {kind} (demo reply) on: {topic.group(1)[:80] if topic else 'the question'}"
            if options:
                pick = options[sum(map(ord, self.member)) % len(options)]
                text += f"\n\nVOTE: {pick}\nCONFIDENCE: 0.{5 + len(self.member) % 5}"
        return LLMResponse(Message(role="assistant", content=text), "end_turn", self.name, self.model)
