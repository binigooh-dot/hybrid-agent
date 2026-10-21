"""[CORE / messages] Provider-neutral message types.

Every backend (Claude, Ollama, OpenAI-compatible servers, the scripted test
backend) converts to and from these classes. The agent loop only ever sees
these, which is what lets us swap models mid-conversation.

NOTE: Claude returns "thinking" blocks that must be passed back unchanged on
later requests. We keep the provider's original content in `Message.raw` and
the Claude backend replays it when `raw_provider == "claude"`. Other backends
ignore `raw` and use the plain `content`/`tool_calls` fields.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A request from the model to run one tool."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    """One turn in the conversation.

    role:
      "user"      - text from the human
      "assistant" - text and/or tool calls from the model
      "tool"      - the result of running one tool call
    """
    role: str
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None   # set on role="tool"
    name: str | None = None           # tool name, set on role="tool"
    is_error: bool = False            # set on role="tool" when the tool failed
    raw: Any = None                   # provider-native content (see module docstring)
    raw_provider: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form used for transcript logs (drops `raw`)."""
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [tc.__dict__ for tc in self.tool_calls]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
            d["name"] = self.name
            d["is_error"] = self.is_error
        return d


@dataclass
class LLMResponse:
    """What every backend's `chat()` returns.

    stop_reason is normalised to one of:
      "end_turn", "tool_use", "max_tokens", "refusal", "other"
    """
    message: Message
    stop_reason: str
    provider: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
