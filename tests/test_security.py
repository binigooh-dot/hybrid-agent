"""[TESTS / security] Hard safety layers: protected paths, sandbox, backups/undo, audit, integrity, safe mode."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hybrid_agent.core.errors import ToolError
from hybrid_agent.security import audit, backup, sandbox
from hybrid_agent.security.guards import check_shell_command, validate_workspace
from hybrid_agent.security.protected import PKG_DIR, protected_targets
from hybrid_agent.tools import ToolContext, build_registry


class ProtectedPathTests(unittest.TestCase):
    def test_modifying_commands_on_protected_paths(self):
        for cmd in ("rm -rf /etc/passwd", "echo x > ~/.bashrc", "chmod 777 /boot", "cp evil $HOME/.ssh/authorized_keys"):
            self.assertTrue(protected_targets(cmd), cmd)

    def test_reading_and_tmp_are_fine(self):
        for cmd in ("cat /etc/hosts", "ls /usr/bin", "echo hi > /tmp/x", "grep foo 2>/dev/null"):
            self.assertEqual(protected_targets(cmd), [], cmd)

    def test_blocklist_refuses_protected_and_internal(self):
        ws = Path(tempfile.mkdtemp())
        with self.assertRaises(ToolError):
            check_shell_command("sed -i s/a/b/ ~/.profile", ws)
        with self.assertRaises(ToolError):
            check_shell_command("rm -rf .agent/backups", ws)

    def test_workspace_cannot_overlap_protected(self):
        for bad in (Path("/etc"), Path.home() / ".ssh", PKG_DIR):
            with self.assertRaises(ValueError):
                validate_workspace(bad)


    def test_agent_installed_under_temp_is_still_protected(self):
        # regression: a temp-folder exemption once let the agent's own code become the workspace
        with mock.patch("tempfile.gettempdir", return_value=str(PKG_DIR.parent)), self.assertRaises(ValueError):
            validate_workspace(PKG_DIR)


class SandboxTests(unittest.TestCase):
    def test_secrets_and_injection_vars_are_stripped(self):
        env = {"PATH": "/usr/bin", "MY_API_KEY": "s", "GITHUB_TOKEN": "t", "LD_PRELOAD": "x.so",
               "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor", "LANG": "C"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(sandbox.clean_env(), {"PATH": "/usr/bin", "LANG": "C"})

    def test_bad_mode_and_required_sandbox(self):
        ws = Path(tempfile.mkdtemp())
        with self.assertRaises(ToolError):
            sandbox.wrap("true", True, ws, mode="bogus")
        with mock.patch.object(sandbox, "strict_available", return_value=None), self.assertRaises(ToolError):
            sandbox.wrap("true", True, ws, require=True)

    @unittest.skipUnless(os.name == "posix", "kernel limits are POSIX-only")
    def test_file_size_limit_is_enforced(self):
        ws = Path(tempfile.mkdtemp())
        cmd, env, shell, _ = sandbox.wrap("head -c 3000000 /dev/zero > big.bin", True, ws, mode="limits",
                                          limits=sandbox.Limits(file_mb=1))
        subprocess.run(cmd, env=env, shell=shell, cwd=ws, capture_output=True, timeout=30, check=False)
        self.assertLessEqual((ws / "big.bin").stat().st_size, 1024 * 1024)

    @unittest.skipUnless(sandbox.strict_available() == "bwrap", "bubblewrap not installed")
    def test_strict_mode_hides_home_and_freezes_system(self):
        ws = Path(tempfile.mkdtemp())
        cmd, env, shell, mode = sandbox.wrap("touch /etc/x 2>/dev/null; echo $?; ls -A ~ | wc -l; touch ok", True, ws,
                                             mode="strict")
        out = subprocess.run(cmd, env=env, shell=shell, cwd=ws, capture_output=True, text=True, timeout=30, check=False)
        code, home_entries = out.stdout.split()[:2]
        self.assertNotEqual(code, "0")
        self.assertLessEqual(int(home_entries), 1)          # at most the read-only .gitconfig
        self.assertTrue((ws / "ok").exists())
        self.assertTrue(mode.startswith("strict"))


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())

    def test_delete_goes_to_trash_and_restores(self):
        d = self.ws / "dir"
        d.mkdir()
        (d / "a.txt").write_text("A")
        e = backup.snapshot(self.ws, d, "delete", move=True)
        self.assertFalse(d.exists())
        self.assertEqual(backup.restore(self.ws, e["id"]), "dir")
        self.assertEqual((d / "a.txt").read_text(), "A")

    def test_restore_backs_up_current_version_first(self):
        f = self.ws / "f.txt"
        f.write_text("old")
        e = backup.snapshot(self.ws, f, "edit")
        f.write_text("new")
        backup.restore(self.ws, e["id"])
        self.assertEqual(f.read_text(), "old")
        self.assertEqual(backup.list_backups(self.ws)[0]["action"], "replaced by restore")

    def test_pruning_and_size_cap(self):
        f = self.ws / "f.txt"
        f.write_text("x" * 100)
        with mock.patch.object(backup, "MAX_BACKUP_BYTES", 250):
            for _ in range(5):
                backup.snapshot(self.ws, f, "edit")
        self.assertEqual(len(backup.list_backups(self.ws)), 2)
        with mock.patch.object(backup, "MAX_SINGLE_BYTES", 10), self.assertRaises(ToolError):
            backup.snapshot(self.ws, f, "edit")

    def test_agent_tools_cannot_touch_backups(self):
        reg = build_registry(ToolContext(workspace=self.ws, approver=lambda *a: True), "full")
        from hybrid_agent.core.messages import ToolCall
        r = reg.execute(ToolCall("1", "write_file", {"path": ".agent/backups/index.json", "content": "[]"}))
        self.assertTrue(r.is_error)


class AuditAndIntegrityTests(unittest.TestCase):
    def test_audit_log_is_redacted(self):
        d = Path(tempfile.mkdtemp())
        audit.record(d, "chat", "run_shell", "execute", {"command": "curl -H 'x-api-key: sk-ant-abcdefghijklmnopqrstuvwxyz'"}, True)
        line = json.loads((d / "audit.jsonl").read_text())
        self.assertEqual(line["tool"], "run_shell")
        self.assertNotIn("abcdefghijklmnop", json.dumps(line))

    def test_manifest_detects_tampering(self):
        root = Path(tempfile.mkdtemp())
        (root / "a.py").write_text("print(1)")
        self.assertEqual(audit.verify_manifest(root)[0], "absent")
        audit.write_manifest(root)
        self.assertEqual(audit.verify_manifest(root)[0], "ok")
        (root / "a.py").write_text("print('pwned')")
        (root / "new.py").write_text("")
        state, detail = audit.verify_manifest(root)
        self.assertEqual(state, "changed")
        self.assertIn("a.py", detail)
        self.assertIn("new.py", detail)


class SafeModeTests(unittest.TestCase):
    def test_safe_mode_has_no_write_or_execute_tools(self):
        reg = build_registry(ToolContext(workspace=Path(tempfile.mkdtemp())), "full", safe_mode=True)
        risks = {t.risk for t in reg.tools()}
        self.assertLessEqual(risks, {"read", "network"})
        self.assertNotIn("run_shell", reg.names())


if __name__ == "__main__":
    unittest.main()
