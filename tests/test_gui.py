"""[TESTS / gui] The local web server: security checks, API, approvals, chat and council jobs.

Runs the real server on a free port with the scripted backend (no model needed).
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from hybrid_agent.core.config import Config
from hybrid_agent.gui.guide import ENV_VARS, build_guide_html
from hybrid_agent.gui.jobs import ApprovalBroker, EventBus
from hybrid_agent.gui.server import create_server


class GuiServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = Path(tempfile.mkdtemp())
        cls.cfg = Config(backend="scripted", workspace=tmp / "ws", log_dir=tmp / "logs", persona_dir=tmp / "personas")
        cls.cfg.workspace.mkdir()
        cls.srv, cls.app = create_server(cls.cfg, port=0)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.app.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, method, path, body=None, token=True, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        if token:
            h["X-Agent-Token"] = self.app.token
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if "json" in resp.headers.get("Content-Type", "") else raw), resp.headers
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, (json.loads(raw) if raw.startswith(b"{") else raw), e.headers

    def wait_job(self, kind, timeout=20):
        q = self.app.bus.subscribe(0)
        try:
            end = time.time() + timeout
            while time.time() < end:
                e = q.get(timeout=timeout)
                if e["type"] in {"job_done", "job_error", "job_cancelled"} and e.get("kind") == kind:
                    return e
        finally:
            self.app.bus.unsubscribe(q)
        self.fail("job did not finish")

    # ------------------------------------------------------------- security
    def test_binds_loopback_only(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_api_requires_token(self):
        self.assertEqual(self.req("GET", "/api/meta", token=False)[0], 401)
        self.assertEqual(self.req("GET", "/api/meta", headers={"X-Agent-Token": "wrong"}, token=False)[0], 401)
        self.assertEqual(self.req("GET", "/api/meta")[0], 200)

    def test_index_needs_token_and_sets_csp(self):
        status, body, _ = self.req("GET", "/", token=False)
        self.assertEqual(status, 401)
        status, body, headers = self.req("GET", f"/?token={self.app.token}", token=False)
        self.assertEqual(status, 200)
        self.assertIn(b"Agent Studio", body)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_dns_rebinding_and_cross_origin_refused(self):
        self.assertEqual(self.req("GET", "/api/meta", headers={"Host": "evil.example:80"})[0], 403)
        self.assertEqual(self.req("POST", "/api/stop", {}, headers={"Origin": "https://evil.example"})[0], 403)

    def test_static_whitelist_and_traversal(self):
        self.assertEqual(self.req("GET", "/static/app.js", token=False)[0], 200)
        for bad in ("/static/../server.py", "/static/index.html", "/static/%2e%2e/server.py"):
            self.assertIn(self.req("GET", bad, token=False)[0], {401, 404}, bad)   # refused either way
            self.assertEqual(self.req("GET", bad)[0], 404, bad)                   # even with the token

    def test_body_limits_and_json(self):
        self.assertEqual(self.req("POST", "/api/face", headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.req("POST", "/api/face", {"face": "x" * 1_100_000})[0], 413)

    def test_persona_ids_cannot_escape_folder(self):
        for bad in ("../evil", "a/b", "UPPER", ""):
            self.assertEqual(self.req("POST", "/api/personas", {"id": bad, "name": "x"})[0], 400, bad)
        self.assertEqual(self.req("DELETE", "/api/personas/..%2Fx")[0], 400)

    def test_face_values_come_from_fixed_menus(self):
        evil = '"/><script>alert(1)</script>'
        status, body, _ = self.req("POST", "/api/face", {"face": {"hair": evil, "color": evil, "eyes": evil}})
        self.assertEqual(status, 200)
        frames = [f for fs in body["faces"].values() for f in fs]
        self.assertTrue(all("<" not in f and len(f.splitlines()) == 7 for f in frames))
        self.assertEqual(len(body["faces"]["speaking"]), 4)       # talking animation
        self.assertEqual(len(body["faces"]["thinking"]), 4)       # deliberating animation

    def test_safety_and_restore(self):
        from hybrid_agent.security.backup import snapshot
        f = self.cfg.workspace / "keep.txt"
        f.write_text("v1")
        entry = snapshot(self.cfg.workspace, f, "edit")
        f.write_text("v2")
        _, s, _ = self.req("GET", "/api/safety")
        self.assertIn(entry["id"], [b["id"] for b in s["backups"]])
        self.assertGreater(s["protected"], 20)
        self.assertEqual(self.req("POST", "/api/restore", {"id": entry["id"]})[1], {"restored": "keep.txt"})
        self.assertEqual(f.read_text(), "v1")
        self.assertEqual(self.req("POST", "/api/restore", {"id": "nope"})[0], 400)

    # ----------------------------------------------------------------- api
    def test_meta_tools_personas(self):
        _, meta, _ = self.req("GET", "/api/meta")
        self.assertIn("roundtable", meta["protocols"])
        self.assertIn("core", meta["profile_tools"])
        _, tools, _ = self.req("GET", "/api/tools")
        self.assertGreaterEqual(len(tools), 75)
        _, personas, _ = self.req("GET", "/api/personas")
        ids = {p["id"] for p in personas}
        self.assertTrue({"sage", "vex", "nova"} <= ids)
        self.assertEqual(len(personas[0]["faces"]), 8)          # 7 expressions + blink

    def test_persona_save_and_delete(self):
        p = {"id": "atlas", "name": "Atlas", "role": "engineer", "face": {"hair": "spiky"}}
        status, saved, _ = self.req("POST", "/api/personas", p)
        self.assertEqual(status, 200)
        self.assertTrue((self.cfg.persona_dir / "atlas.json").exists())
        self.assertEqual(self.req("DELETE", "/api/personas/atlas")[1], {"deleted": True})

    def test_chat_job(self):
        status, body, _ = self.req("POST", "/api/chat", {"message": "demo"})
        self.assertEqual(status, 202)
        e = self.wait_job("chat")
        self.assertEqual(e["type"], "job_done")
        self.assertIn("Demo complete", e["result"]["answer"])

    def test_council_job_and_busy(self):
        status, _, _ = self.req("POST", "/api/council", {"question": "Rust or Go?", "personas": ["sage", "vex", "nova"],
                                                          "protocol": "vote", "options": ["Rust", "Go"]})
        self.assertEqual(status, 202)
        e = self.wait_job("council")
        self.assertEqual(e["type"], "job_done", e)
        self.assertIn(e["result"]["tally"]["winner"], {"Rust", "Go", None})
        self.assertTrue(Path(e["result"]["transcript"]).exists())

    def test_bad_council_requests(self):
        self.assertEqual(self.req("POST", "/api/council", {"question": "", "personas": ["sage"]})[0], 400)
        self.assertEqual(self.req("POST", "/api/council", {"question": "q", "personas": ["nobody"]})[0], 400)
        self.assertEqual(self.req("POST", "/api/council", {"question": "q", "personas": ["sage"], "protocol": "x"})[0], 400)

    def test_guide_served_with_nonce(self):
        status, body, headers = self.req("GET", f"/guide?token={self.app.token}", token=False)
        self.assertEqual(status, 200)
        nonce = headers["Content-Security-Policy"].split("'nonce-")[1].split("'")[0]
        self.assertIn(f'nonce="{nonce}"'.encode(), body)


class BrokerTests(unittest.TestCase):
    def test_approval_roundtrip_and_timeout_denies(self):
        bus = EventBus()
        broker = ApprovalBroker(bus, timeout=5)
        q = bus.subscribe()
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("v", broker.approver("x")("run_shell", {"c": 1}, "r")))
        t.start()
        ev = q.get(timeout=2)
        self.assertEqual(ev["type"], "approval_request")
        broker.answer(ev["request_id"], True)
        t.join(3)
        self.assertTrue(out["v"])
        quick = ApprovalBroker(bus, timeout=0.2)
        self.assertFalse(quick.approver("x")("run_shell", {}, "r"))  # silence = deny

    def test_job_is_idle_when_done_is_announced(self):
        from hybrid_agent.gui.jobs import JobManager
        bus = EventBus()
        jobs = JobManager(bus, ApprovalBroker(bus))
        q = bus.subscribe()
        jobs.start("x", lambda: 1)
        while q.get(timeout=2)["type"] != "job_done":
            pass
        self.assertIsNone(jobs.status(), "a client reacting to job_done must be able to start the next job")
        jobs.start("y", lambda: 2)  # must not raise JobBusy

    def test_events_are_redacted(self):
        bus = EventBus()
        e = bus.publish("agent", text="key sk-ant-api03-" + "A" * 40)
        self.assertNotIn("AAAA", json.dumps(e))


class GuideTests(unittest.TestCase):
    def test_guide_builds_and_embeds_everything(self):
        html = build_guide_html()
        for s in ("Tool explorer", "Profile builder", "Council designer", "Safety centre", "read_file", "Sage"):
            self.assertIn(s, html)
        self.assertNotIn("%%", html)

    def test_env_vars_documented(self):
        root = Path(__file__).resolve().parent.parent
        keys = {line.split("=")[0].lstrip("# ").strip() for line in (root / ".env.example").read_text().splitlines()
                if "=" in line and line.lstrip("# ").split("=")[0].strip().isupper()}
        self.assertEqual(keys - {k for k, _, _ in ENV_VARS}, set())


if __name__ == "__main__":
    unittest.main()
