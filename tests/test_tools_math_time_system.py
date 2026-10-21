"""[TESTS / tools: math + time + system + agent ops]"""
from __future__ import annotations

import json
import os
import unittest

from hybrid_agent.tools.builtin.math_time import convert_units, safe_eval

from .helpers import ToolTestCase


class MathToolTests(ToolTestCase, unittest.TestCase):
    def test_calculator_is_safe(self):
        self.assertEqual(safe_eval("2**10 + sqrt(16)"), 1028.0)
        self.assertEqual(safe_eval("2^3"), 8)
        for bad in ("__import__('os')", "1/0", "9**99999", "open('x')"):
            self.assertTrue(self.call("calculator", expression=bad).is_error, bad)

    def test_statistics(self):
        s = json.loads(self.ok("statistics", numbers=[1, 2, 3, 4, 100]))
        self.assertEqual((s["median"], s["max"], s["count"]), (3, 100, 5))

    def test_units(self):
        self.assertAlmostEqual(convert_units(1, "mi", "km"), 1.609344)
        self.assertAlmostEqual(convert_units(100, "c", "f"), 212)
        self.assertAlmostEqual(convert_units(1, "gib", "mb"), 1073.741824)
        self.assertTrue(self.call("unit_convert", value=1, from_unit="kg", to_unit="km").is_error)

    def test_bases(self):
        self.assertEqual(self.ok("convert_base", number="ff", from_base=16, to_base=2), "11111111")
        self.assertEqual(self.ok("convert_base", number="0", from_base=10, to_base=7), "0")


class TimeToolTests(ToolTestCase, unittest.TestCase):
    def test_dates(self):
        d = json.loads(self.ok("date_calc", start="2026-01-01", end="2026-03-01"))
        self.assertEqual(d["days"], 59)
        self.assertEqual(self.ok("date_calc", start="2026-01-30", add_days=3), "Monday 2026-02-02")
        self.assertIn("2026", self.ok("current_time", timezone="Asia/Tokyo"))
        self.assertTrue(self.call("current_time", timezone="Mars/Base").is_error)

    def test_timezone(self):
        self.assertIn("18:00", self.ok("convert_timezone", datetime="2026-06-01T09:00", from_tz="UTC",
                                       to_tz="Asia/Tokyo"))


class SystemToolTests(ToolTestCase, unittest.TestCase):
    def test_info_and_env_redaction(self):
        self.assertIn('"cpus"', self.ok("system_info"))
        self.assertIn("free", self.ok("disk_usage"))
        os.environ["HA_SECRET_TOKEN"] = "s3cr3t"
        try:
            out = self.ok("env_vars", contains="HA_SECRET")
            self.assertIn("<hidden>", out)
            self.assertNotIn("s3cr3t", out)
        finally:
            del os.environ["HA_SECRET_TOKEN"]
        self.assertTrue(self.call("python_packages", contains="zzz-no-such-pkg").is_error)


class AgentOpsToolTests(ToolTestCase, unittest.TestCase):
    def test_plan_think_ask(self):
        self.assertIn("[x] a", self.ok("update_plan", items=[{"task": "a", "status": "done"},
                                                             {"task": "b", "status": "pending"}]))
        self.assertEqual(self.ok("think", thought="hmm"), "Noted.")
        self.assertIn("No user", self.ok("ask_user", question="?"))
        self.assertTrue(self.call("delegate_to_local", task="x").is_error)  # no local backend in ctx


if __name__ == "__main__":
    unittest.main()
