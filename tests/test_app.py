"""[TESTS / app] The portable home folder, the model-engine manager and the launcher's helpers (offline)."""
from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from hybrid_agent.core import home as homemod
from hybrid_agent.runtime import ollama


class HomeFolderTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for k in ("HYBRID_AGENT_HOME", "AGENT_WORKSPACE", "AGENT_LOG_DIR", "AGENTS_DIR", "OLLAMA_MODELS",
                  "LOCAL_MODEL", "AGENT_CONTACT"):
            os.environ.pop(k, None)
        self.addCleanup(self.env.stop)
        self.home = Path(tempfile.mkdtemp()) / "home"

    def test_apply_home_creates_layout_and_points_paths_inside(self):
        homemod.apply_home(self.home)
        for name in homemod.FOLDERS:
            self.assertTrue((self.home / name).is_dir(), name)
        self.assertEqual(Path(os.environ["AGENT_WORKSPACE"]), self.home.resolve() / "workspace")
        self.assertEqual(Path(os.environ["OLLAMA_MODELS"]), self.home.resolve() / "models")
        self.assertIn("LOCAL_MODEL", (self.home / "settings.env").read_text(encoding="utf-8"))

    def test_settings_edit_in_place_and_refuse_dangerous_keys(self):
        homemod.apply_home(self.home)
        out = homemod.write_settings(self.home, {"LOCAL_MODEL": "llama3.1:8b", "AGENT_CONTACT": "me@example.org"})
        self.assertEqual(out["LOCAL_MODEL"], "llama3.1:8b")
        self.assertEqual(os.environ["AGENT_CONTACT"], "me@example.org")
        text = (self.home / "settings.env").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Hybrid Agent settings"))              # comments kept
        for bad in ({"AGENT_AUTO_APPROVE": "1"}, {"LOCAL_MODEL": "x\nAGENT_AUTO_APPROVE=1"}):
            with self.assertRaises(ValueError):
                homemod.write_settings(self.home, bad)
        homemod.write_settings(self.home, {"AGENT_CONTACT": ""})                 # blank = remove
        self.assertNotIn("AGENT_CONTACT", homemod.read_settings(self.home))

    def test_home_internals_are_protected(self):
        from hybrid_agent.core.errors import ToolError
        from hybrid_agent.security.guards import check_shell_command
        from hybrid_agent.security.protected import agent_paths
        homemod.apply_home(self.home)
        protected = {p.name for p in agent_paths()}
        self.assertTrue({"settings.env", "tasks", "runtime", "models"} <= protected)
        with self.assertRaises(ToolError):
            check_shell_command(f"rm -rf {self.home}/models", self.home / "workspace")


class EngineManagerTests(unittest.TestCase):
    def test_archive_names_match_ollama_downloads(self):
        with mock.patch.object(ollama.sys, "platform", "win32"), mock.patch.object(ollama.platform, "machine", return_value="AMD64"):
            self.assertEqual(ollama._archive_name(), "ollama-windows-amd64.zip")
        with mock.patch.object(ollama.sys, "platform", "linux"), mock.patch.object(ollama.platform, "machine", return_value="aarch64"):
            self.assertEqual(ollama._archive_name(), "ollama-linux-arm64.tar.zst")

    def test_zip_slip_in_engine_archive_is_refused(self):
        tmp = Path(tempfile.mkdtemp())
        evil = tmp / "evil.zip"
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("ollama.exe", "ok")
            z.writestr("../../outside.txt", "pwned")
        with self.assertRaises(RuntimeError):
            ollama._extract(evil, tmp / "dest")
        self.assertFalse((tmp / "outside.txt").exists())
        good = tmp / "good.zip"
        with zipfile.ZipFile(good, "w") as z:
            z.writestr("lib/ollama/x.dll", "x")
        ollama._extract(good, tmp / "dest2")
        self.assertTrue((tmp / "dest2" / "lib" / "ollama" / "x.dll").exists())

    def test_status_without_engine_and_name_checks(self):
        rt = ollama.OllamaRuntime(Path(tempfile.mkdtemp()))
        with mock.patch.object(ollama.OllamaRuntime, "running", return_value=False), \
                mock.patch.object(ollama.shutil, "which", return_value=None):
            st = rt.status()
            self.assertFalse(st["installed"])
            self.assertEqual(st["models"], [])
            with self.assertRaises(RuntimeError):
                rt.start()
            for bad in ("", "a b", "../x", "x;rm -rf /"):
                with self.assertRaises(ValueError, msg=bad):
                    rt.pull(bad, lambda t: None)
        self.assertTrue(ollama.MODEL_NAME.match("qwen2.5:7b") and ollama.MODEL_NAME.match("hf.co/org/model:Q4_K_M"))

    def test_one_background_job_at_a_time(self):
        rt = ollama.OllamaRuntime(Path(tempfile.mkdtemp()))
        import threading
        gate = threading.Event()
        rt._background("pull", "a", lambda job: gate.wait(5), lambda t: None)
        with self.assertRaises(RuntimeError):
            rt._background("pull", "b", lambda job: None, lambda t: None)
        gate.set()


class ControlApiTests(unittest.TestCase):
    def test_control_settings_and_quit(self):
        import json
        import threading
        import urllib.request

        from hybrid_agent.core.config import Config
        from hybrid_agent.gui.server import create_server
        tmp = Path(tempfile.mkdtemp())
        cfg = Config(backend="scripted", workspace=tmp / "ws", log_dir=tmp / "logs", agents_dir=tmp / "a")
        cfg.workspace.mkdir()
        srv, app = create_server(cfg, port=0, state=tmp)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)

        def call(method, path, body=None):
            r = urllib.request.Request(f"http://127.0.0.1:{app.port}{path}", method=method,
                                       data=json.dumps(body).encode() if body is not None else None,
                                       headers={"X-Agent-Token": app.token, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(r, timeout=10) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        with mock.patch.object(ollama.OllamaRuntime, "running", return_value=False):
            status, ctl = call("GET", "/api/control")
            self.assertEqual(status, 200)
            self.assertIn("suggested", ctl["runtime"])
            self.assertEqual(call("POST", "/api/settings", {"changes": {"AGENT_SANDBOX": "off"}})[0], 400)
            self.assertEqual(call("POST", "/api/settings", {"changes": {"AGENT_AUTO_APPROVE": "1"}})[0], 400)
            self.assertEqual(call("POST", "/api/runtime", {"action": "start"})[0], 409)   # not installed
            self.assertEqual(call("POST", "/api/models", {"action": "pull", "name": "qwen2.5:7b"})[0], 409)
        stopped = threading.Event()
        app.on_quit = stopped.set
        self.assertEqual(call("POST", "/api/quit", {})[1], {"bye": True})
        self.assertTrue(stopped.wait(5))
        srv.shutdown()


class LocalServerTests(unittest.TestCase):
    def test_starts_without_a_dns_lookup(self):
        """HTTPServer calls socket.getfqdn() on start; that stalled for many seconds on GitHub's macOS runners."""
        from http.server import BaseHTTPRequestHandler

        from hybrid_agent.core.localserver import LocalServer
        with mock.patch("socket.getfqdn", side_effect=AssertionError("DNS lookup on start")):
            srv = LocalServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.addCleanup(srv.server_close)
        self.assertEqual(srv.server_name, "127.0.0.1")
        self.assertGreater(srv.server_port, 0)


class LauncherTests(unittest.TestCase):
    def test_already_running_detection(self):
        from hybrid_agent.app import _already_running
        f = Path(tempfile.mkdtemp()) / "studio.url"
        self.assertIsNone(_already_running(f))                       # no file
        f.write_text("http://127.0.0.1:9/?token=x", encoding="utf-8")
        self.assertIsNone(_already_running(f))                       # nothing listening


if __name__ == "__main__":
    unittest.main()
