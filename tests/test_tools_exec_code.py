"""[TESTS / tools: shell + code]"""
from __future__ import annotations

import shutil
import unittest

from .helpers import ToolTestCase


class ShellToolTests(ToolTestCase, unittest.TestCase):
    def test_shell_python_which(self):
        self.assertIn("hi", self.ok("run_shell", command="echo hi"))
        self.assertIn("4", self.ok("run_python", code="print(2+2)"))
        self.assertTrue(self.call("run_shell", command="rm -rf /").is_error)
        self.assertIn("NOT FOUND", self.ok("which", programs=["definitely-not-a-program-xyz"]))

    def test_timeout(self):
        r = self.call("run_python", code="import time; time.sleep(5)", timeout=1)
        self.assertTrue(r.is_error)
        self.assertIn("Timed out", r.content)


class CodeToolTests(ToolTestCase, unittest.TestCase):
    def test_outline(self):
        self.ok("write_file", path="m.py", content='class A:\n    def f(self, x=1):\n        """Does f."""\n'
                                                   'async def g(): pass\n')
        out = self.ok("code_outline", path="m.py")
        self.assertIn("L1 class A", out)
        self.assertIn("def f(self, x=1)  # Does f.", out)
        self.assertIn("async def g()", out)
        self.ok("write_file", path="m.js", content="export function hello() {}\nconst x = 1\n")
        self.assertIn("L1 export function hello", self.ok("code_outline", path="m.js"))

    def test_check_syntax(self):
        self.ok("write_file", path="bad.py", content="def x(:\n")
        self.assertIn("SYNTAX ERROR", self.ok("check_syntax", path="bad.py"))
        self.ok("write_file", path="ok.json", content='{"a": 1}')
        self.assertIn("OK", self.ok("check_syntax", path="ok.json"))
        self.ok("write_file", path="bad.json", content='{"a": }')
        self.assertIn("JSON ERROR", self.ok("check_syntax", path="bad.json"))
        self.assertTrue(self.call("check_syntax", path="ok.json.txt").is_error)

    def test_run_tests(self):
        self.ok("write_file", path="t/test_x.py", content="import unittest\nclass T(unittest.TestCase):\n"
                                                         "    def test_a(self): self.assertTrue(True)\n")
        self.assertIn("exit code: 0", self.ok("run_tests", path="t"))

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_git_flow(self):
        self.ok("run_shell", command="git init -q && git config user.email t@t && git config user.name t")
        self.ok("write_file", path="f.txt", content="1\n")
        self.assertIn("?? f.txt", self.ok("git_status"))
        self.assertIn("exit code: 0", self.ok("git_commit", message="first"))
        self.assertIn("first", self.ok("git_log"))
        self.ok("edit_file", path="f.txt", old_text="1", new_text="2")
        self.assertIn("+2", self.ok("git_diff"))


if __name__ == "__main__":
    unittest.main()
