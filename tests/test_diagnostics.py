"""[TESTS / diagnostics] Every safety drill must pass, and the drills must be meaningful.

The drills simulate attacks and failures in throwaway sandboxes (see
hybrid_agent/diagnostics). Running them as tests means a code change that
weakens a defence fails the test-suite.
"""
from __future__ import annotations

import unittest

from hybrid_agent.core.errors import ToolError
from hybrid_agent.diagnostics.drills import DRILLS
from hybrid_agent.diagnostics.harness import (
    NetworkTripwire,
    ProcessTripwire,
    TripwireTriggered,
)
from hybrid_agent.diagnostics.integrity import CHECKS
from hybrid_agent.diagnostics.runner import run_drill
from hybrid_agent.security.guards import check_shell_command


class DrillTests(unittest.TestCase):
    def test_every_drill_passes(self):
        for d in DRILLS:
            with self.subTest(drill=d.key):
                r = run_drill(d)
                self.assertTrue(r.passed, f"{d.key}: {r.detail}")

    def test_integrity_checks_pass(self):
        for name, fn in CHECKS:
            ok, detail = fn()
            self.assertTrue(ok, f"{name}: {detail}")

    def test_drill_catalogue_is_well_formed(self):
        keys = [d.key for d in DRILLS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertGreaterEqual(len(DRILLS), 25)
        for d in DRILLS:
            self.assertIn(d.severity, {"critical", "high", "medium"})
            self.assertTrue(d.scenario)


class HarnessTests(unittest.TestCase):
    """The harness is what makes drills safe; prove it works."""

    def test_process_tripwire_refuses_destructive(self):
        import subprocess
        with ProcessTripwire(), self.assertRaises(TripwireTriggered):
            subprocess.Popen(["rm", "-rf", "/nonexistent-drill-path"])

    def test_network_tripwire_blocks_non_loopback(self):
        import socket
        with NetworkTripwire() as net, self.assertRaises(OSError):
            socket.create_connection(("10.255.255.1", 80), timeout=1)
        self.assertTrue(net.tried("10.255.255.1"))

    def test_checker_refuses_without_executing(self):
        with self.assertRaises(ToolError):
            check_shell_command("rm -rf ~/")


if __name__ == "__main__":
    unittest.main()
