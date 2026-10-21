"""[TESTS / tools: data + text]"""
from __future__ import annotations

import json
import unittest

from .helpers import ToolTestCase

CSV = "name,city,amount\nAnn,Paris,10\nBob,Rome,25.5\nCid,Paris,4\n"


class DataToolTests(ToolTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        (self.ws / "s.csv").write_text(CSV)

    def test_csv_read(self):
        out = self.ok("csv_read", path="s.csv")
        self.assertIn("3 rows", out)
        self.assertIn("amount: numeric, min 4, max 25.5", out)

    def test_csv_query(self):
        out = self.ok("csv_query", path="s.csv", where=["city == Paris"], sort_by="-amount")
        self.assertIn("2 matching rows", out)
        self.assertLess(out.index("Ann"), out.index("Cid"))
        agg = self.ok("csv_query", path="s.csv", group_by="city", aggregate="sum", value_column="amount")
        self.assertIn("| Paris | 14.0 |", agg)
        self.assertTrue(self.call("csv_query", path="s.csv", where=["nope > 1"]).is_error)

    def test_json_and_convert(self):
        self.ok("convert_data", source="s.csv", destination="s.json")
        self.assertEqual(self.ok("json_query", path="s.json", query="[1].name"), "Bob")
        self.assertEqual(json.loads(self.ok("json_query", path="s.json", query="*.city")),
                         ["Paris", "Rome", "Paris"])
        self.ok("convert_data", source="s.json", destination="back.csv")
        self.assertIn("Bob,Rome,25.5", (self.ws / "back.csv").read_text())

    def test_sqlite(self):
        self.ok("sqlite_query", path="db.sqlite", sql="CREATE TABLE t (x INTEGER)")
        self.ok("sqlite_query", path="db.sqlite", sql="INSERT INTO t VALUES (1), (2)")
        self.assertIn("| 3 |", self.ok("sqlite_query", path="db.sqlite", sql="SELECT sum(x) AS s FROM t"))
        self.assertTrue(self.call("sqlite_query", path="db.sqlite", sql="SELECT * FROM missing").is_error)

    def test_xml(self):
        (self.ws / "b.xml").write_text('<lib><book lang="en"><title>A</title></book>'
                                       '<book lang="fr"><title>B</title></book></lib>')
        self.assertEqual(self.ok("xml_query", path="b.xml", xpath=".//book[@lang='fr']/title"), "<title> B")
        self.assertEqual(self.ok("xml_query", path="b.xml", xpath=".//book[@lang='en']"), '<book lang="en">')


class TextToolTests(ToolTestCase, unittest.TestCase):
    def test_stats_regex_entities(self):
        self.assertIn('"words": 4', self.ok("text_stats", text="Hello world. Hello again!"))
        self.assertIn("groups=('12',)", self.ok("regex_find", pattern=r"(\d+)", text="a 12 b"))
        ent = json.loads(self.ok("extract_entities", text="Mail a@b.com or see https://x.org on 2026-01-02"))
        self.assertEqual(ent["emails"], ["a@b.com"])
        self.assertEqual(ent["urls"], ["https://x.org"])
        self.assertEqual(ent["dates"], ["2026-01-02"])

    def test_regex_replace_file(self):
        self.ok("write_file", path="r.txt", content="v1 v2 v3")
        self.assertIn("3 replacement", self.ok("regex_replace_file", path="r.txt", pattern=r"v(\d)",
                                                replacement=r"version-\1"))
        self.assertEqual((self.ws / "r.txt").read_text(), "version-1 version-2 version-3")

    def test_encode_hash_ids_compare(self):
        b64 = self.ok("encode_decode", text="hi there", codec="base64", direction="encode")
        self.assertEqual(self.ok("encode_decode", text=b64, codec="base64", direction="decode"), "hi there")
        self.assertEqual(self.ok("encode_decode", text="a b", codec="url", direction="encode"), "a%20b")
        self.assertEqual(self.ok("hash_text", text="abc", algorithm="md5"), "900150983cd24fb0d6963f7d28e17f72")
        self.ok("write_file", path="h.txt", content="abc")
        self.assertIn("ba7816bf", self.ok("hash_file", path="h.txt"))
        self.assertEqual(len(self.ok("generate_id", kind="password", length=20)), 20)
        self.assertEqual(len(self.ok("generate_id", kind="uuid", count=3).splitlines()), 3)
        self.assertIn("similarity", self.ok("compare_text", text_a="abc", text_b="abd"))


if __name__ == "__main__":
    unittest.main()
