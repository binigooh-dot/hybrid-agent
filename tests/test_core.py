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
from hybrid_agent.security.guards import check_shell_command, resolve_in_workspace

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


class ContextTrimTests(unittest.TestCase):
    def _agent(self, backend):
        return Agent(backend, make_registry(), context_chars=5000)

    def test_old_tool_output_is_shortened_for_local_models(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "big.txt").write_text("x" * 3000 + "\n", encoding="utf-8")
        calls = [Message(role="assistant", tool_calls=[ToolCall(str(i), "read_file", {"path": "big.txt", "limit": 1})])
                 for i in range(8)]
        reg = make_registry(tmp)
        agent = Agent(ScriptedBackend([*calls, Message(role="assistant", content="done")]), reg, context_chars=12000)
        agent.messages.extend(Message(role="tool", content="y" * 3000, tool_call_id=f"o{i}", name="read_file")
                              for i in range(6))
        agent.run("go")
        trimmed = [m for m in agent.messages if m.role == "tool" and m.content.startswith("[older tool output")]
        recent = [m for m in agent.messages if m.role == "tool"][-4:]
        self.assertTrue(trimmed, "old tool results should be shortened")
        self.assertFalse(any(m.content.startswith("[older") for m in recent), "recent results stay whole")

    def test_claude_history_is_never_trimmed(self):
        class ClaudeLike(ScriptedBackend):
            allows_history_trim = False
        agent = Agent(ClaudeLike([Message(role="assistant", content="ok")]), make_registry(), context_chars=100)
        agent.messages.append(Message(role="tool", content="z" * 5000, tool_call_id="1", name="x"))
        agent.run("hi")
        self.assertEqual(agent.messages[0].content, "z" * 5000)


class ConfigTests(unittest.TestCase):
    def test_validate(self):
        from hybrid_agent.core.config import Config
        Config().validate()
        for bad in ({"backend": "gpt"}, {"max_steps": 0}, {"local_base_url": "file:///x"}, {"claude_effort": "huge"}):
            with self.assertRaises(ValueError, msg=bad):
                Config(**bad).validate()

    def test_dotenv_inline_comments(self):
        f = Path(tempfile.mkdtemp()) / ".env"
        f.write_text('HA_T1=ollama   # comment\nHA_T2="a # b"\n# HA_T3=x\n', encoding="utf-8")
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


class PortabilityTests(unittest.TestCase):
    """Windows reads files in the old regional code page unless told otherwise: always say UTF-8."""

    def test_every_text_file_operation_names_its_encoding(self):
        import ast
        root = Path(__file__).resolve().parent.parent / "hybrid_agent"
        missing = []
        for f in root.rglob("*.py"):
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if not isinstance(n, ast.Call) or any(k.arg == "encoding" for k in n.keywords):
                    continue
                name = getattr(n.func, "attr", getattr(n.func, "id", ""))
                if name in ("read_text", "write_text"):
                    missing.append(f"{f.relative_to(root)}:{n.lineno}")
                elif name == "open":
                    if isinstance(n.func, ast.Attribute) and getattr(n.func.value, "id", "") in {"tarfile", "zipfile", "gzip", "zstd", "os", "webbrowser"}:
                        continue                               # archives / OS handles: binary or not text files
                    if isinstance(n.func, ast.Name):            # builtin open(path, mode)
                        mode = n.args[1] if len(n.args) > 1 else None
                    elif not n.args:                           # Path.open() = read text
                        mode = ast.Constant("r")
                    elif isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                        mode = n.args[0]                       # Path.open("a")
                    else:
                        continue                               # e.g. urllib opener.open(request): not a file
                    if not (isinstance(mode, ast.Constant) and "b" in str(mode.value)):
                        missing.append(f"{f.relative_to(root)}:{n.lineno}")
        self.assertEqual(missing, [])

    def test_internal_python_mode_speaks_utf8(self):
        import subprocess
        import sys

        from hybrid_agent.core.pyexe import emulate
        self.assertEqual(emulate(["-X", "utf8", "-I", "-c", "import sys; sys.exit(3)"]), 3)
        out = subprocess.run([sys.executable, "-X", "utf8", "-I", "-c", "print('╭─╮ ● é')"], capture_output=True,
                             check=False).stdout.decode("utf-8")
        self.assertIn("╭─╮ ● é", out)
