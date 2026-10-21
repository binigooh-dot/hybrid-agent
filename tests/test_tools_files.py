"""[TESTS / tools: files + archives]"""
from __future__ import annotations

import unittest

from .helpers import ToolTestCase, make_registry


class FileToolTests(ToolTestCase, unittest.TestCase):
    def test_write_read_edit_append(self):
        self.ok("write_file", path="a/b.txt", content="one\ntwo\n")
        self.assertIn("2  two", self.ok("read_file", path="a/b.txt"))
        self.ok("edit_file", path="a/b.txt", old_text="two", new_text="TWO")
        self.ok("append_file", path="a/b.txt", content="three\n")
        self.assertEqual((self.ws / "a/b.txt").read_text(), "one\nTWO\nthree\n")
        self.assertIn("2 more lines", self.ok("read_file", path="a/b.txt", limit=1))

    def test_edit_errors_are_helpful(self):
        self.ok("write_file", path="x.txt", content="aa aa")
        self.assertIn("appears 2 times", self.call("edit_file", path="x.txt", old_text="aa", new_text="b").content)
        self.assertIn("not found", self.call("edit_file", path="x.txt", old_text="zz", new_text="b").content)

    def test_find_search_tree_info(self):
        self.ok("write_file", path="src/m.py", content="def foo():\n    return 1\n")
        (self.ws / "bin.dat").write_bytes(b"foo\0\1\2")
        self.assertIn("src/m.py", self.ok("find_files", pattern="*.py"))
        hits = self.ok("search_text", regex="foo")
        self.assertIn("src/m.py:1", hits)
        self.assertNotIn("bin.dat", hits, "binary files must be skipped")
        self.assertIn("└── m.py", self.ok("tree"))
        self.assertIn('"lines": 2', self.ok("file_info", path="src/m.py"))
        self.assertTrue(self.call("read_file", path="bin.dat").is_error)

    def test_copy_move_delete_diff(self):
        self.ok("write_file", path="a.txt", content="x\ny\n")
        self.ok("copy_path", source="a.txt", destination="b.txt")
        self.ok("edit_file", path="b.txt", old_text="y", new_text="z")
        self.assertIn("+z", self.ok("diff_files", path_a="a.txt", path_b="b.txt"))
        self.ok("make_dir", path="d")
        self.ok("move_path", source="b.txt", destination="d/b.txt")
        self.assertTrue((self.ws / "d/b.txt").exists())
        self.ok("delete_path", path="d")
        self.assertFalse((self.ws / "d").exists())
        self.assertTrue(self.call("delete_path", path=".").is_error)

    def test_sandbox_blocks_escape(self):
        r = self.call("read_file", path="../../etc/passwd")
        self.assertTrue(r.is_error)
        self.assertIn("outside the workspace", r.content)
        self.assertTrue(self.call("write_file", path="/etc/evil", content="x").is_error)

    def test_overwrite_needs_approval(self):
        self.ok("write_file", path="k.txt", content="1")
        r = make_registry(self.tmp, approve=False).execute(
            __import__("hybrid_agent.core.messages", fromlist=["ToolCall"]).ToolCall(
                "t", "write_file", {"path": "k.txt", "content": "2"}))
        self.assertTrue(r.is_error)
        self.assertEqual((self.ws / "k.txt").read_text(), "1")


class ArchiveToolTests(ToolTestCase, unittest.TestCase):
    def test_zip_and_tar_roundtrip(self):
        self.ok("write_file", path="p/one.txt", content="1")
        self.ok("write_file", path="p/two.txt", content="2")
        for name in ("p.zip", "p.tar.gz"):
            self.assertIn("2 files", self.ok("archive_create", output=name, paths=["p"]))
            self.assertIn("p/one.txt", self.ok("archive_list", path=name))
            out = name.replace(".", "_")
            self.ok("archive_extract", path=name, destination=out)
            self.assertEqual((self.ws / out / "p/two.txt").read_text(), "2")

    def test_zip_slip_blocked(self):
        import zipfile
        with zipfile.ZipFile(self.ws / "evil.zip", "w") as z:
            z.writestr("../../escape.txt", "x")
        r = self.call("archive_extract", path="evil.zip")
        self.assertTrue(r.is_error)
        self.assertIn("escape", r.content)


if __name__ == "__main__":
    unittest.main()
