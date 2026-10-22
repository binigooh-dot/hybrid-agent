"""[TESTS / tools: framework] Registry, validation, profiles, and schema<->signature consistency."""
from __future__ import annotations

import unittest
from pathlib import Path

from hybrid_agent.core.messages import ToolCall
from hybrid_agent.tools import (
    PROFILES,
    S,
    ToolContext,
    build_full_registry,
    build_registry,
)
from hybrid_agent.tools.profiles import apply_profile
from hybrid_agent.tools.registry import RISK_LEVELS, check_signature, validate_args

from .helpers import make_registry


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.reg = build_full_registry(ToolContext(Path(".")))

    def test_every_schema_matches_its_function(self):
        problems = [p for n in self.reg.names() for p in check_signature(self.reg.get(n))]
        self.assertEqual(problems, [])

    def test_every_tool_is_labelled(self):
        for n in self.reg.names():
            t = self.reg.get(n)
            self.assertIn(t.risk, RISK_LEVELS)
            self.assertNotEqual(t.category, "misc", n)
            self.assertGreater(len(t.description), 15, n)

    def test_large_suite(self):
        self.assertGreaterEqual(len(self.reg), 75)
        self.assertGreaterEqual(len(self.reg.categories()), 15)

    def test_validation(self):
        schema = S(path="string", n="integer?", mode={"type": "string", "enum": ["a", "b"], "optional": True})
        self.assertEqual(validate_args(schema, {}), ["missing required argument 'path'"])
        self.assertIn("argument 'n' should be integer, got str", validate_args(schema, {"path": "x", "n": "3"}))
        self.assertIn("unknown argument 'pth' (valid: path, n, mode)", validate_args(schema, {"path": "x", "pth": 1}))
        self.assertTrue(validate_args(schema, {"path": "x", "mode": "c"}))
        self.assertEqual(validate_args(S(x="number"), {"x": 3}), [])

    def test_unknown_tool_and_crash_are_errors_not_exceptions(self):
        reg = make_registry()
        self.assertTrue(reg.execute(ToolCall("t", "nope", {})).is_error)

        @reg.tool("boom", "Always raises an exception", S(), category="test")
        def boom(ctx):
            raise RuntimeError("kaboom")
        r = reg.execute(ToolCall("t", "boom", {}))
        self.assertTrue(r.is_error)
        self.assertIn("kaboom", r.content)

    def test_approval_declined(self):
        r = make_registry(approve=False).execute(ToolCall("t", "run_shell", {"command": "echo hi"}))
        self.assertTrue(r.is_error)
        self.assertIn("declined", r.content)

    def test_output_truncation(self):
        reg = make_registry(max_output=50)
        self.assertIn("truncated", reg.execute(ToolCall("t", "generate_id", {"kind": "uuid", "count": 10})).content)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.ctx = ToolContext(Path("."))

    def test_all_profiles_build_and_reference_real_tools(self):
        full = build_full_registry(self.ctx)
        for name, p in PROFILES.items():
            for tool in p.get("names", []):
                self.assertIn(tool, full, f"profile {name} names unknown tool {tool}")
            self.assertGreater(len(build_registry(self.ctx, name)), 0)

    def test_curated_profiles_stay_small_for_local_models(self):
        for name in ("minimal", "core", "research", "coding", "data", "readonly"):
            self.assertLessEqual(len(build_registry(self.ctx, name)), 25, name)

    def test_readonly_has_no_write_or_execute(self):
        for prof in ("readonly", "readonly_all"):
            reg = build_registry(self.ctx, prof)
            self.assertFalse([n for n in reg.names() if reg[n].risk in {"write", "execute"}], prof)

    def test_modifiers(self):
        full = build_full_registry(self.ctx)
        reg = apply_profile(full, "core,+weather,-run_shell,@archives")
        self.assertIn("weather", reg)
        self.assertNotIn("run_shell", reg)
        self.assertIn("archive_list", reg)
        for bad in ("nope", "core,+nope", "core,@nope", "core,weather"):
            with self.assertRaises(ValueError, msg=bad):
                apply_profile(full, bad)

    def test_delegate_only_when_asked(self):
        self.assertNotIn("delegate_to_local", build_registry(self.ctx, "full"))
        self.assertIn("delegate_to_local", build_registry(self.ctx, "core", include_delegate=True))

    def test_full_excludes_council_board(self):
        self.assertNotIn("board_post", build_registry(self.ctx, "full"))


class DocsTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent

    def test_every_python_file_is_labelled(self):
        import ast
        unlabelled = []
        for f in self.ROOT.rglob("*.py"):
            if {"workspace", "logs", ".git"} & set(f.parts) or (f.name == "__init__.py" and f.parent.name == "tests"):
                continue
            doc = ast.get_docstring(ast.parse(f.read_text(encoding="utf-8"))) or ""
            if not doc.startswith("["):
                unlabelled.append(str(f.relative_to(self.ROOT)))
        self.assertEqual(unlabelled, [], "start each module docstring with a [LAYER / name] label")


if __name__ == "__main__":
    unittest.main()
