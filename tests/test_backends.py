"""[TESTS / backends] Local backend over fake HTTP servers, Claude message conversion, router, spec factory."""
from __future__ import annotations

import json
import unittest

from hybrid_agent.backends import (
    BackendUnavailable,
    CannedBackend,
    LocalBackend,
    RouterBackend,
    ScriptedBackend,
    build_backend_from_spec,
)
from hybrid_agent.backends.claude import to_anthropic_messages
from hybrid_agent.backends.local import parse_prompted_tool_calls
from hybrid_agent.cli.doctor import model_available
from hybrid_agent.core.agent import Agent
from hybrid_agent.core.config import Config
from hybrid_agent.core.messages import Message, ToolCall

from .helpers import QuietHandler, make_registry, serve


class FakeLLM(QuietHandler):
    """Pretends to be Ollama (/api/chat) or an OpenAI-compatible server.
    First request -> a tool call; second -> a final answer. `no_tools=True`
    mimics a model without native tool support."""
    requests: list = []
    no_tools = False

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append((self.path, body))
        if self.no_tools and "tools" in body:
            return self.send(400, {"error": "registry.ollama.ai/x does not support tools"})
        if body["model"] == "missing":
            return self.send(404, {"error": "model 'missing' not found"})
        has_result = any(m["role"] == "tool" or (m["content"] or "").startswith("TOOL RESULT")
                         for m in body["messages"])
        if self.path == "/api/chat":
            if has_result:
                msg = {"role": "assistant", "content": "The answer is 42."}
            elif self.no_tools:
                msg = {"role": "assistant",
                       "content": '```json\n{"tool": "calculator", "arguments": {"expression": "6*7"}}\n```'}
            else:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"function": {"name": "calculator", "arguments": {"expression": "6*7"}}}]}
            return self.send(200, {"message": msg, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5})
        if self.path == "/v1/chat/completions":
            if has_result:
                msg = {"role": "assistant", "content": "The answer is 42."}
            else:
                msg = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "calculator", "arguments": '{"expression": "6*7"}'}}]}
            return self.send(200, {"choices": [{"message": msg, "finish_reason": "stop"}],
                                   "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        self.send(404, {"error": "not found"})


class LocalBackendHTTPTests(unittest.TestCase):
    def server(self, no_tools=False):
        handler = type("H", (FakeLLM,), {"requests": [], "no_tools": no_tools})
        return serve(self, handler), handler

    def run_agent(self, backend):
        return Agent(backend, make_registry()).run("what is 6*7?")

    def test_ollama_native_tools(self):
        url, h = self.server()
        self.assertEqual(self.run_agent(LocalBackend("m", url, "ollama")), "The answer is 42.")
        self.assertEqual(h.requests[1][1]["messages"][-1],
                         {"role": "tool", "content": "42", "tool_name": "calculator"})

    def test_openai_compatible(self):
        url, h = self.server()
        self.assertEqual(self.run_agent(LocalBackend("m", url, "openai")), "The answer is 42.")
        self.assertEqual(h.requests[1][1]["messages"][-1]["tool_call_id"], "call_1")

    def test_auto_switches_to_prompt_mode(self):
        url, _ = self.server(no_tools=True)
        b = LocalBackend("m", url, "ollama", tool_mode="auto")
        self.assertEqual(self.run_agent(b), "The answer is 42.")
        self.assertEqual(b.tool_mode, "prompt")

    def test_missing_model_message(self):
        url, _ = self.server()
        with self.assertRaisesRegex(BackendUnavailable, "ollama pull missing"):
            LocalBackend("missing", url).chat("s", [Message(role="user", content="x")])

    def test_server_down_is_unavailable(self):
        with self.assertRaises(BackendUnavailable):
            LocalBackend("m", "http://127.0.0.1:9", timeout=2).chat("s", [Message(role="user", content="x")])


class ConversionTests(unittest.TestCase):
    def test_prompt_mode_parser(self):
        rest, calls = parse_prompted_tool_calls(
            'Sure.\n```json\n{"tool": "calculator", "arguments": {"expression": "1+1"}}\n```')
        self.assertEqual((rest, calls[0].name), ("Sure.", "calculator"))
        self.assertEqual(parse_prompted_tool_calls('{"tool": "current_time", "arguments": {}}')[1][0].name,
                         "current_time")
        self.assertEqual(parse_prompted_tool_calls("just text")[1], [])

    def test_claude_merges_parallel_tool_results(self):
        out = to_anthropic_messages([
            Message(role="user", content="q"),
            Message(role="assistant", tool_calls=[ToolCall("a", "x", {}), ToolCall("b", "y", {})]),
            Message(role="tool", content="1", tool_call_id="a", name="x"),
            Message(role="tool", content="2", tool_call_id="b", name="y", is_error=True),
        ])
        self.assertEqual(len(out), 3)
        self.assertEqual([b["tool_use_id"] for b in out[2]["content"]], ["a", "b"])
        self.assertTrue(out[2]["content"][1]["is_error"])

    def test_claude_replays_raw_blocks(self):
        raw = [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": "hi"}]
        out = to_anthropic_messages([Message(role="user", content="q"),
                                     Message(role="assistant", content="hi", raw=raw, raw_provider="claude")])
        self.assertIs(out[1]["content"], raw)


class RouterAndFactoryTests(unittest.TestCase):
    def test_router_falls_back(self):
        class Broken(ScriptedBackend):
            def chat(self, *a, **k):
                raise BackendUnavailable("offline")
        local = ScriptedBackend([Message(role="assistant", content="from local")])
        router = RouterBackend(Broken([]), local)
        self.assertEqual(router.chat("s", [Message(role="user", content="hi")]).message.content, "from local")
        self.assertIs(router.last_used, local)

    def test_backend_specs(self):
        cfg = Config(local_model="base")
        self.assertEqual(build_backend_from_spec("local:llama3.1:8b", cfg).model, "llama3.1:8b")
        self.assertEqual(build_backend_from_spec("local", cfg).model, "base")
        self.assertIsInstance(build_backend_from_spec("scripted", cfg), CannedBackend)
        self.assertIsInstance(build_backend_from_spec("default", Config(backend="scripted")), CannedBackend)
        self.assertIsInstance(build_backend_from_spec("local:x", Config(backend="scripted")), CannedBackend)
        with self.assertRaises(ValueError):
            build_backend_from_spec("gpt:4", cfg)

    def test_doctor_model_matching(self):
        self.assertTrue(model_available("qwen2.5:7b", ["qwen2.5:7b"]))
        self.assertTrue(model_available("qwen2.5", ["qwen2.5:latest"]))
        self.assertFalse(model_available("qwen2.5", ["qwen2.5:14b"]))


if __name__ == "__main__":
    unittest.main()
