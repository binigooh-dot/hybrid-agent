"""[BACKENDS / local] Local model backend - the piece that makes the agent work with NO API key.

Supports two kinds of local server, both spoken to with the standard library
(urllib), so nothing needs to be pip-installed:

  provider="ollama"  ->  POST {base}/api/chat            (Ollama)
  provider="openai"  ->  POST {base}/v1/chat/completions (llama.cpp server,
                          LM Studio, vLLM, LocalAI, Jan... anything
                          "OpenAI-compatible" running on your machine)

Tool calling has two modes:

  native - the server's own tool-calling support (best when the model has it:
           qwen2.5, llama3.1+, mistral-nemo, etc.)
  prompt - we describe the tools in the system prompt and ask the model to
           reply with a JSON block, which we parse ourselves. Works with ANY
           instruction-following model, just less reliably.

  auto   - try native; if the server says the model doesn't support tools,
           switch to prompt mode for the rest of the session.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid
from typing import Any

from ..core.messages import LLMResponse, Message, ToolCall
from .base import Backend, BackendUnavailable

PROMPT_TOOL_INSTRUCTIONS = """\
You can use tools. To call a tool, reply with ONLY a fenced JSON block like:

```json
{"tool": "<tool name>", "arguments": {<arguments>}}
```

You may call several tools by putting several such blocks in one reply.
After a tool runs you will receive its result in a message that starts with
"TOOL RESULT". When you have the final answer, reply normally with no JSON block.

Available tools:
"""

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _new_id() -> str:
    return "call_" + uuid.uuid4().hex[:12]


def parse_prompted_tool_calls(text: str) -> tuple[str, list[ToolCall]]:
    """Pull {"tool": ..., "arguments": ...} blocks out of free text.

    Returns (remaining_text, tool_calls). Also accepts a bare JSON object as
    the whole reply, since small models often forget the code fence.
    """
    calls: list[ToolCall] = []
    candidates = _JSON_BLOCK.findall(text)
    stripped = text.strip()
    if not candidates and stripped.startswith("{") and stripped.endswith("}"):
        candidates = [stripped]
    for blob in candidates:
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        name = obj.get("tool") or obj.get("name")
        if not isinstance(name, str):
            continue
        args = obj.get("arguments") or obj.get("args") or obj.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls.append(ToolCall(id=_new_id(), name=name, arguments=args))
    remaining = _JSON_BLOCK.sub("", text).strip() if calls else text
    if calls and remaining.startswith("{"):
        remaining = ""
    return remaining, calls


class LocalBackend(Backend):
    allows_history_trim = True
    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        provider: str = "ollama",
        tool_mode: str = "auto",
        timeout: float = 300.0,
        num_ctx: int = 8192,
    ):
        if provider not in {"ollama", "openai"}:
            raise ValueError(f"unknown local provider {provider!r}")
        if tool_mode not in {"auto", "native", "prompt"}:
            raise ValueError(f"unknown tool mode {tool_mode!r}")
        if not base_url.startswith(("http://", "https://")):
            raise ValueError(f"LOCAL_BASE_URL must start with http:// or https:// (got {base_url!r})")
        self.name = f"local-{provider}"
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.tool_mode = tool_mode
        self.timeout = timeout
        self.num_ctx = num_ctx

    # ------------------------------------------------------------------ HTTP
    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            # Reviewed (B310): scheme validated in __init__
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # nosec B310
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise _HTTPError(e.code, body) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise BackendUnavailable(
                f"local model server at {self.base_url} unreachable: {e}. "
                "Is the model engine running? Press Set up now in the app (or run `ollama serve`)."
            ) from None

    # ------------------------------------------------------------ public API
    def chat(self, system, messages, tools=None) -> LLMResponse:
        use_native = bool(tools) and self.tool_mode in {"auto", "native"}
        try:
            return self._chat(system, messages, tools, native=use_native)
        except _HTTPError as e:
            if use_native and self.tool_mode == "auto" and _looks_like_no_tool_support(e.body):
                # Remember for the rest of the session so we don't pay the
                # failed round-trip every turn.
                self.tool_mode = "prompt"
                return self._chat(system, messages, tools, native=False)
            if e.status == 404 and "model" in e.body.lower():
                raise BackendUnavailable(
                    f"model {self.model!r} not found on the local server. "
                    f"Download it with Set up now in the app (or `ollama pull {self.model}`)."
                ) from None
            raise BackendUnavailable(f"local server error {e.status}: {e.body[:500]}") from None

    def _chat(self, system, messages, tools, native: bool) -> LLMResponse:
        use_tools = bool(tools) and native
        if tools and not native:
            system = system + "\n\n" + PROMPT_TOOL_INSTRUCTIONS + "\n".join(json.dumps(t) for t in tools)
        wire = self._to_wire(system, messages, native)
        request = self._ollama_request if self.provider == "ollama" else self._openai_request
        text, raw_calls, finish, usage = request(wire, [_fn_spec(t) for t in tools] if use_tools and tools else None)
        calls = [self._parse_call(rc) for rc in raw_calls]
        if tools and not native:
            text, calls = parse_prompted_tool_calls(text)
        stop = "tool_use" if calls else ("max_tokens" if finish == "length" else "end_turn")
        return LLMResponse(message=Message(role="assistant", content=text, tool_calls=calls),
                           stop_reason=stop, provider=self.name, model=self.model, usage=usage)

    # One adapter per server dialect. Each returns (text, raw tool calls, finish reason, usage).
    def _ollama_request(self, wire: list[dict], fn_tools: list[dict] | None):
        payload: dict[str, Any] = {"model": self.model, "messages": wire, "stream": False,
                                   "options": {"num_ctx": self.num_ctx}}
        if fn_tools:
            payload["tools"] = fn_tools
        data = self._post("/api/chat", payload)
        msg = data.get("message", {})
        usage = {"input_tokens": data.get("prompt_eval_count", 0), "output_tokens": data.get("eval_count", 0)}
        return msg.get("content") or "", msg.get("tool_calls") or [], data.get("done_reason", "stop"), usage

    def _openai_request(self, wire: list[dict], fn_tools: list[dict] | None):
        payload: dict[str, Any] = {"model": self.model, "messages": wire}
        if fn_tools:
            payload["tools"] = fn_tools
        data = self._post("/v1/chat/completions", payload)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {})
        u = data.get("usage") or {}
        usage = {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)}
        return msg.get("content") or "", msg.get("tool_calls") or [], choice.get("finish_reason", "stop"), usage

    @staticmethod
    def _parse_call(rc: dict) -> ToolCall:
        fn = rc.get("function", {})
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError:
                args = {"_raw": args}
        if not isinstance(args, dict):
            args = {"_raw": args}
        return ToolCall(id=rc.get("id") or _new_id(), name=fn.get("name", ""), arguments=args)

    # ------------------------------------------------------------ conversion
    def _to_wire(self, system: str, messages: list[Message], native: bool) -> list[dict]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                if native and m.tool_calls:
                    out.append({
                        "role": "assistant", "content": m.content,
                        "tool_calls": [self._wire_call(tc) for tc in m.tool_calls],
                    })
                elif m.tool_calls:
                    # Prompt mode: show the model its own earlier JSON calls.
                    blocks = "\n".join(
                        "```json\n" + json.dumps({"tool": tc.name, "arguments": tc.arguments}) + "\n```"
                        for tc in m.tool_calls)
                    out.append({"role": "assistant", "content": (m.content + "\n" + blocks).strip()})
                else:
                    out.append({"role": "assistant", "content": m.content})
            elif m.role == "tool":
                if native:
                    entry = {"role": "tool", "content": m.content}
                    if self.provider == "ollama":
                        entry["tool_name"] = m.name or ""
                    else:
                        entry["tool_call_id"] = m.tool_call_id or ""
                    out.append(entry)
                else:
                    status = "ERROR" if m.is_error else "OK"
                    out.append({"role": "user",
                                "content": f"TOOL RESULT ({m.name}, {status}):\n{m.content}"})
        return out

    def _wire_call(self, tc: ToolCall) -> dict[str, Any]:
        if self.provider == "ollama":
            return {"function": {"name": tc.name, "arguments": tc.arguments}}
        return {"id": tc.id, "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}

    # ------------------------------------------------------------- one-shot
    def complete(self, prompt: str, system: str = "You are a helpful assistant.") -> str:
        """Single prompt -> text. Used by the delegate tool."""
        return self.chat(system, [Message(role="user", content=prompt)]).message.content


class _HTTPError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status, self.body = status, body


def _looks_like_no_tool_support(body: str) -> bool:
    b = body.lower()
    return "does not support tools" in b or ("tool" in b and "not support" in b)


def _fn_spec(t: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
