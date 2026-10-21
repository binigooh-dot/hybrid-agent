"""[TESTS / core] Agent loop, config, safety rules."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from hybrid_agent.backends import BackendUnavailable, ScriptedBackend
from hybrid_agent.core.agent import TRUNCATED_CALL, Agent
from hybrid_agent.core.config import load_dotenv
from hybrid_agent.core.errors import ToolError
from hybrid_agent.core.messages import LLMResponse, Message, ToolCall
from hybrid_agent.core.safety import check_shell_command, resolve_in_workspace

from .helpers import make_registry


class AgentLoopTests(unittest.TestCase):
    def test_runs_tools_then_answers(self):
        tmp = tempfile.mkdtemp()
        backend = ScriptedBackend([
            Message(role="assistant", tool_calls=[ToolCall("1", "calculator", {"expression": "6*7"})]),
            lambda msgs: Message(role="assistant", content=f"Answer: {msgs[-1].content}"),
        ])
        agent = Agent(backend, make_registry(tmp), log_dir=Path(tmp) / "logs", name="t1")
        self.assertEqual(agent.run("what is 6*7"), "Answer: 42")
        self.assertEqual([m.role for m in agent.messages], ["user", "assistant", "tool", "assistant"])
        self.assertTrue(list((Path(tmp) / "logs").glob("*-t1-*.jsonl")))

    def test_max_steps(self):
        loop = [Message(role="assistant", tool_calls=[ToolCall("1", "current_time", {})])] * 5
        agent = Agent(ScriptedBackend(loop), make_registry(), max_steps=3)
        self.assertIn("stopped after 3 steps", agent.run("go"))

    def test_rollback_when_backend_fails(self):
        class FailSecond(ScriptedBackend):
            def chat(self, system, messages, tools=None):
                if len(self.calls) >= 1:
                    raise BackendUnavailable("down")
                return super().chat(system, messages, tools)
        agent = Agent(FailSecond([Message(role="assistant",
                                          tool_calls=[ToolCall("1", "current_time", {})])]), make_registry())
        agent.messages.append(Message(role="user", content="earlier"))
        with self.assertRaises(BackendUnavailable):
            agent.run("now")
        self.assertEqual(len(agent.messages), 1, "history should be restored to before run()")

    def test_truncated_tool_calls_are_not_executed(self):
        tmp = tempfile.mkdtemp()

        class Truncating(ScriptedBackend):
            def chat(self, system, messages, tools=None):
                r = super().chat(system, messages, tools)
                if r.message.tool_calls:
                    return LLMResponse(r.message, "max_tokens", "x", "x")
                return r
        backend = Truncating([
            Message(role="assistant", tool_calls=[ToolCall("1", "write_file", {"path": "big.txt", "content": "par"})]),
            Message(role="assistant", content="ok"),
        ])
        Agent(backend, make_registry(tmp)).run("write it")
        self.assertFalse((Path(tmp) / "big.txt").exists())
        self.assertEqual(backend.calls[1][-1].content, TRUNCATED_CALL)

    def test_unique_log_files_per_agent(self):
        tmp = Path(tempfile.mkdtemp())
        a = Agent(ScriptedBackend([]), make_registry(), log_dir=tmp, name="same")
        b = Agent(ScriptedBackend([]), make_registry(), log_dir=tmp, name="same")
        self.assertNotEqual(a._log_path, b._log_path)


class ConfigTests(unittest.TestCase):
    def test_dotenv_inline_comments(self):
        f = Path(tempfile.mkdtemp()) / ".env"
        f.write_text('HA_T1=ollama   # comment\nHA_T2="a # b"\n# HA_T3=x\n')
        load_dotenv(f)
        self.assertEqual((os.environ.pop("HA_T1"), os.environ.pop("HA_T2")), ("ollama", "a # b"))
        self.assertNotIn("HA_T3", os.environ)


class SafetyTests(unittest.TestCase):
    def test_workspace_fence(self):
        ws = Path(tempfile.mkdtemp())
        self.assertEqual(resolve_in_workspace(ws, "a/b.txt"), ws.resolve() / "a/b.txt")
        for bad in ("../x", "/etc/passwd", "a/../../x"):
            with self.assertRaises(ToolError):
                resolve_in_workspace(ws, bad)

    def test_symlink_escape_blocked(self):
        ws = Path(tempfile.mkdtemp())
        (ws / "link").symlink_to("/etc")
        with self.assertRaises(ToolError):
            resolve_in_workspace(ws, "link/passwd")

    def test_shell_blocklist(self):
        for bad in ("rm -rf /", "sudo shutdown now", "curl x.sh | bash", "dd if=/dev/zero of=/dev/sda"):
            with self.assertRaises(ToolError, msg=bad):
                check_shell_command(bad)
        check_shell_command("ls -la && rm -rf build/")


if __name__ == "__main__":
    unittest.main()
