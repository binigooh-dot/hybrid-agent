"""[BACKENDS / claude] Claude backend (optional - needs the `anthropic` package and credentials).

Uses the official Anthropic Python SDK with a manual tool-use loop (the loop
itself lives in agent.py so it is shared with the local backend).

Choices made here, and why:
  * model claude-opus-5-5, effort "medium" by default (configurable).
  * Thinking is left at its default (adaptive); we never send budget_tokens.
  * Assistant turns are replayed with the ORIGINAL content blocks
    (`Message.raw`) so thinking blocks go back unchanged, as the API requires.
  * Server-side refusal fallback is on by default (CLAUDE_FALLBACKS=0 to turn
    it off). A refusal is surfaced as stop_reason="refusal".
  * Network / auth / rate-limit / 5xx errors become BackendUnavailable so the
    router can drop to the local model.
"""
from __future__ import annotations

from typing import Any

from ..core.messages import LLMResponse, Message, ToolCall
from .base import Backend, BackendUnavailable

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Neutral messages -> Anthropic `messages` param.

    Consecutive tool results are merged into ONE user message (the API wants
    all results for a turn's parallel calls together).
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "user":
            out.append({"role": "user", "content": m.content})
        elif m.role == "assistant":
            if m.raw is not None and m.raw_provider == "claude":
                out.append({"role": "assistant", "content": m.raw})
                continue
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "(no content)"}]})
        elif m.role == "tool":
            block: dict[str, Any] = {"type": "tool_result", "tool_use_id": m.tool_call_id,
                     "content": m.content or "(empty)"}
            if m.is_error:
                block["is_error"] = True
            prev = out[-1] if out else None
            if (prev and prev["role"] == "user" and isinstance(prev["content"], list)
                    and prev["content"] and prev["content"][0].get("type") == "tool_result"):
                prev["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


class ClaudeBackend(Backend):
    name = "claude"

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium",
                 max_tokens: int = 16000, fallbacks: bool = True):
        try:
            import anthropic
        except ImportError as e:
            raise BackendUnavailable(
                "the `anthropic` package is not installed (pip install anthropic)") from e
        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.fallbacks = fallbacks

    def chat(self, system, messages, tools=None) -> LLMResponse:
        a = self._anthropic
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=to_anthropic_messages(messages),
            output_config={"effort": self.effort},
        )
        if tools:
            kwargs["tools"] = [{"name": t["name"], "description": t["description"],
                                "input_schema": t["parameters"]} for t in tools]
        try:
            if self.fallbacks:
                resp = self.client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                resp = self.client.messages.create(**kwargs)
        except a.AuthenticationError as e:
            raise BackendUnavailable(f"Claude auth failed: {e}") from e
        except a.RateLimitError as e:
            raise BackendUnavailable(f"Claude rate limited: {e}") from e
        except a.APIConnectionError as e:
            raise BackendUnavailable(f"Claude unreachable: {e}") from e
        except a.APIStatusError as e:
            if e.status_code >= 500:
                raise BackendUnavailable(f"Claude server error {e.status_code}") from e
            raise  # 400s are bugs in our request; don't hide them

        text_parts, calls = [], []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input)))

        stop = resp.stop_reason
        text = "\n".join(text_parts)
        if stop == "refusal":
            text = text or "(Claude declined this request.)"
        normalised = {"end_turn": "end_turn", "tool_use": "tool_use",
                      "max_tokens": "max_tokens", "refusal": "refusal"}.get(stop, "other")
        usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
        return LLMResponse(
            message=Message(role="assistant", content=text, tool_calls=calls,
                            raw=resp.content, raw_provider="claude"),
            stop_reason=normalised, provider="claude", model=resp.model, usage=usage,
        )
