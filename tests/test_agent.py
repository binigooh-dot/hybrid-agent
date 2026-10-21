"""Test-suite. Runs fully offline: no API key, no model, no internet.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from hybrid_agent.agent import Agent
from hybrid_agent.backends import BackendUnavailable, LocalBackend, RouterBackend, ScriptedBackend
from hybrid_agent.backends.claude import to_anthropic_messages
from hybrid_agent.backends.local import parse_prompted_tool_calls
from hybrid_agent.messages import Message, ToolCall
from hybrid_agent.tools import ToolContext, build_default_registry
from hybrid_agent.tools.registry import validate_args
from hybrid_agent.tools.utilities import safe_eval
from hybrid_agent.tools.web import html_to_text


def make_registry(tmp: str, approve: bool = True, **kw):
    ctx = ToolContext(workspace=Path(tmp), approver=lambda *a: approve, **kw)
    return build_default_registry(ctx, include_delegate=True)


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.reg = make_registry(self.tmp)

    def call(self, name, **args):
        return self.reg.execute(ToolCall("t", name, args))

    def test_write_read_edit(self):
        self.assertFalse(self.call("write_file", path="a/b.txt", content="one\ntwo\n").is_error)
        self.assertIn("2  two", self.call("read_file", path="a/b.txt").content)
        self.assertFalse(self.call("edit_file", path="a/b.txt", old_text="two", new_text="TWO").is_error)
        self.assertEqual((Path(self.tmp) / "a/b.txt").read_text(), "one\nTWO\n")
        self.assertIn("b.txt", self.call("find_files", pattern="*.txt").content)
        self.assertIn("a/b.txt:2", self.call("search_text", regex="TWO").content)

    def test_sandbox_blocks_escape(self):
        r = self.call("read_file", path="../../etc/passwd")
        self.assertTrue(r.is_error)
        self.assertIn("outside the workspace", r.content)
        self.assertTrue(self.call("write_file", path="/etc/evil", content="x").is_error)

    def test_validation_errors_are_reported(self):
        r = self.call("read_file")
        self.assertTrue(r.is_error)
        self.assertIn("missing required argument 'path'", r.content)
        self.assertTrue(self.reg.execute(ToolCall("t", "nope", {})).is_error)
        self.assertEqual(validate_args({"properties": {"n": {"type": "integer"}}}, {"n": "3"}),
                         ["argument 'n' should be integer, got str"])

    def test_shell_and_python(self):
        self.assertIn("hi", self.call("run_shell", command="echo hi").content)
        self.assertIn("4", self.call("run_python", code="print(2+2)").content)
        self.assertTrue(self.call("run_shell", command="rm -rf /").is_error)

    def test_approval_declined(self):
        reg = make_registry(self.tmp, approve=False)
        r = reg.execute(ToolCall("t", "run_shell", {"command": "echo hi"}))
        self.assertTrue(r.is_error)
        self.assertIn("declined", r.content)

    def test_memory_roundtrip(self):
        self.call("remember", key="fav_colour", value="green", tags=["prefs"])
        self.assertIn("green", self.call("recall", query="colour").content)
        self.assertIn("green", self.call("recall", query="prefs").content)
        self.call("forget", key="fav_colour")
        self.assertIn("Nothing", self.call("recall", query="colour").content)

    def test_calculator_is_safe(self):
        self.assertEqual(safe_eval("2**10 + sqrt(16)"), 1028.0)
        self.assertTrue(self.call("calculator", expression="__import__('os')").is_error)
        self.assertTrue(self.call("calculator", expression="1/0").is_error)

    def test_plan(self):
        r = self.call("update_plan", items=[{"task": "a", "status": "done"},
                                            {"task": "b", "status": "pending"}])
        self.assertIn("[x] a", r.content)

    def test_output_truncation(self):
        reg = make_registry(self.tmp, max_output=50)
        r = reg.execute(ToolCall("t", "run_python", {"code": "print('x'*500)"}))
        self.assertIn("truncated", r.content)

    def test_html_to_text(self):
        t = html_to_text("<html><head><script>x()</script></head><body><h1>Hi</h1><p>there</p></body></html>")
        self.assertEqual(t, "Hi\nthere")


class ConfigTests(unittest.TestCase):
    def test_dotenv_inline_comments(self):
        import os
        from hybrid_agent.config import load_dotenv
        f = Path(tempfile.mkdtemp()) / ".env"
        f.write_text('HA_T1=ollama   # comment\nHA_T2="a # b"\n# HA_T3=x\n')
        load_dotenv(f)
        self.assertEqual((os.environ.pop("HA_T1"), os.environ.pop("HA_T2")), ("ollama", "a # b"))
        self.assertNotIn("HA_T3", os.environ)


class AgentLoopTests(unittest.TestCase):
    def test_loop_runs_tools_then_answers(self):
        tmp = tempfile.mkdtemp()
        backend = ScriptedBackend([
            Message(role="assistant", tool_calls=[ToolCall("1", "calculator", {"expression": "6*7"})]),
            lambda msgs: Message(role="assistant", content=f"Answer: {msgs[-1].content}"),
        ])
        agent = Agent(backend, make_registry(tmp), log_dir=Path(tmp) / "logs")
        self.assertEqual(agent.run("what is 6*7"), "Answer: 42")
        roles = [m.role for m in agent.messages]
        self.assertEqual(roles, ["user", "assistant", "tool", "assistant"])
        self.assertTrue(list((Path(tmp) / "logs").glob("*.jsonl")))

    def test_max_steps(self):
        loop = [Message(role="assistant", tool_calls=[ToolCall("1", "current_time", {})])] * 5
        agent = Agent(ScriptedBackend(loop), make_registry(tempfile.mkdtemp()), max_steps=3)
        self.assertIn("stopped after 3 steps", agent.run("go"))


class RouterTests(unittest.TestCase):
    def test_falls_back(self):
        class Broken(ScriptedBackend):
            def chat(self, *a, **k):
                raise BackendUnavailable("offline")
        local = ScriptedBackend([Message(role="assistant", content="from local")])
        router = RouterBackend(Broken([]), local)
        self.assertEqual(router.chat("s", [Message(role="user", content="hi")]).message.content, "from local")
        self.assertIs(router.last_used, local)


class ConversionTests(unittest.TestCase):
    def test_prompt_mode_parser(self):
        text = 'Sure.\n```json\n{"tool": "calculator", "arguments": {"expression": "1+1"}}\n```'
        rest, calls = parse_prompted_tool_calls(text)
        self.assertEqual(rest, "Sure.")
        self.assertEqual(calls[0].name, "calculator")
        _, calls = parse_prompted_tool_calls('{"tool": "current_time", "arguments": {}}')
        self.assertEqual(calls[0].name, "current_time")
        self.assertEqual(parse_prompted_tool_calls("just text")[1], [])

    def test_claude_merges_parallel_tool_results(self):
        msgs = [
            Message(role="user", content="q"),
            Message(role="assistant", tool_calls=[ToolCall("a", "x", {}), ToolCall("b", "y", {})]),
            Message(role="tool", content="1", tool_call_id="a", name="x"),
            Message(role="tool", content="2", tool_call_id="b", name="y", is_error=True),
        ]
        out = to_anthropic_messages(msgs)
        self.assertEqual(len(out), 3)
        self.assertEqual([b["tool_use_id"] for b in out[2]["content"]], ["a", "b"])
        self.assertTrue(out[2]["content"][1]["is_error"])

    def test_claude_replays_raw_blocks(self):
        raw = [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": "hi"}]
        out = to_anthropic_messages([Message(role="user", content="q"),
                                     Message(role="assistant", content="hi", raw=raw, raw_provider="claude")])
        self.assertIs(out[1]["content"], raw)


# ---------------------------------------------------------------- fake servers
class _FakeLLMHandler(BaseHTTPRequestHandler):
    """Pretends to be Ollama (/api/chat) or an OpenAI-compatible server.
    First request -> a tool call; second -> a final answer. Set
    `no_tools=True` to mimic a model without native tool support."""
    requests: list = []
    no_tools = False

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append((self.path, body))
        if self.no_tools and "tools" in body:
            return self._send(400, {"error": "registry.ollama.ai/x does not support tools"})
        has_result = any(m["role"] == "tool" or m["content"].startswith("TOOL RESULT")
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
            return self._send(200, {"message": msg, "done_reason": "stop",
                                    "prompt_eval_count": 10, "eval_count": 5})
        if self.path == "/v1/chat/completions":
            if has_result:
                msg = {"role": "assistant", "content": "The answer is 42."}
            else:
                msg = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "calculator", "arguments": '{"expression": "6*7"}'}}]}
            return self._send(200, {"choices": [{"message": msg, "finish_reason": "stop"}],
                                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        self._send(404, {"error": "not found"})

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class LocalBackendHTTPTests(unittest.TestCase):
    def serve(self, no_tools=False):
        handler = type("H", (_FakeLLMHandler,), {"requests": [], "no_tools": no_tools})
        srv = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_port}", handler

    def run_agent(self, backend):
        return Agent(backend, make_registry(tempfile.mkdtemp())).run("what is 6*7?")

    def test_ollama_native_tools(self):
        url, h = self.serve()
        self.assertEqual(self.run_agent(LocalBackend("m", url, "ollama")), "The answer is 42.")
        second = h.requests[1][1]["messages"]
        self.assertEqual(second[-1], {"role": "tool", "content": "42", "tool_name": "calculator"})

    def test_openai_compatible(self):
        url, h = self.serve()
        self.assertEqual(self.run_agent(LocalBackend("m", url, "openai")), "The answer is 42.")
        self.assertEqual(h.requests[1][1]["messages"][-1]["tool_call_id"], "call_1")

    def test_auto_switches_to_prompt_mode(self):
        url, _ = self.serve(no_tools=True)
        b = LocalBackend("m", url, "ollama", tool_mode="auto")
        self.assertEqual(self.run_agent(b), "The answer is 42.")
        self.assertEqual(b.tool_mode, "prompt")

    def test_server_down_is_unavailable(self):
        with self.assertRaises(BackendUnavailable):
            LocalBackend("m", "http://127.0.0.1:9", timeout=2).chat("s", [Message(role="user", content="x")])


if __name__ == "__main__":
    unittest.main()
