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
from hybrid_agent.gui.jobs import ApprovalBroker, EventBus
from hybrid_agent.gui.server import create_server


class GuiServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = Path(tempfile.mkdtemp())
        cls.cfg = Config(backend="scripted", workspace=tmp / "ws", log_dir=tmp / "logs", agents_dir=tmp / "agents")
        cls.cfg.workspace.mkdir()
        cls.srv, cls.app = create_server(cls.cfg, port=0, state=tmp)
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

    def wait_job(self, kind, job_id=None, timeout=20):
        q = self.app.bus.subscribe(0)
        try:
            end = time.time() + timeout
            while time.time() < end:
                e = q.get(timeout=timeout)
                if e["type"] in {"job_done", "job_error", "job_cancelled"} and e.get("kind") == kind \
                        and job_id in (None, e.get("job_id")):
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
        self.assertIn(b"Hybrid Agent", body)
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

    def test_agent_ids_cannot_escape_folder(self):
        for bad in ("../evil", "a/b", "UPPER"):
            self.assertEqual(self.req("POST", "/api/agents", {"id": bad, "name": "x"})[0], 400, bad)
        self.assertEqual(self.req("DELETE", "/api/agents/..%2Fx")[0], 400)
        self.assertEqual(self.req("POST", "/api/agents", {"name": "x", "model": "local:$(rm -rf /)"})[0], 400)

    def test_face_values_come_from_fixed_menus(self):
        evil = '"/><script>alert(1)</script>'
        status, body, _ = self.req("POST", "/api/face", {"face": {"top": evil, "color": evil, "eyes": evil}})
        self.assertEqual(status, 200)
        frames = [f for fs in body["faces"].values() for f in fs]
        self.assertTrue(all("<" not in f and len(f.splitlines()) == 7 for f in frames))
        self.assertTrue(all(32 <= ord(c) < 127 for f in frames for c in f.replace("\n", "")), "plain ASCII only")
        self.assertEqual(len(body["faces"]["talking"]), 4)        # mouth opens and closes
        self.assertEqual(len(body["faces"]["thinking"]), 4)

    def test_safety_and_restore(self):
        from hybrid_agent.security.backup import snapshot
        f = self.cfg.workspace / "keep.txt"
        f.write_text("v1", encoding="utf-8")
        entry = snapshot(self.cfg.workspace, f, "edit")
        f.write_text("v2", encoding="utf-8")
        _, s, _ = self.req("GET", "/api/safety")
        self.assertIn(entry["id"], [b["id"] for b in s["backups"]])
        self.assertGreater(s["protected"], 20)
        self.assertEqual(self.req("POST", "/api/restore", {"id": entry["id"]})[1], {"restored": "keep.txt"})
        self.assertEqual(f.read_text(encoding="utf-8"), "v1")
        self.assertEqual(self.req("POST", "/api/restore", {"id": "nope"})[0], 400)

    # ----------------------------------------------------------------- api
    def test_meta_and_agents(self):
        _, meta, _ = self.req("GET", "/api/meta")
        self.assertIn("roundtable", meta["protocols"])
        self.assertEqual(set(meta["face_parts"]), {"top", "eyes", "mouth", "colors"})
        _, agents, _ = self.req("GET", "/api/agents")
        self.assertEqual([a["id"] for a in agents][:3], ["blue", "green", "orange"])
        self.assertEqual(len(agents[0]["faces"]), 6)              # 5 expressions + blink
        self.assertEqual(self.req("GET", "/api/tools")[0], 404)   # the tool browser is gone

    def test_agent_create_edit_and_delete(self):
        status, saved, _ = self.req("POST", "/api/agents", {"name": "Atlas", "face": {"top": "spikes", "eyes": "@"}})
        self.assertEqual((status, saved["id"]), (200, "atlas"))
        self.assertTrue((self.cfg.agents_dir / "atlas.json").exists())
        self.assertEqual(self.req("POST", "/api/agents", {"name": "Atlas"})[1]["id"], "atlas-2")   # no clobbering
        self.assertEqual(self.req("POST", "/api/agents", {"id": "atlas", "name": "Atlas", "model": "scripted"})[1]["model"],
                         "scripted")
        self.assertEqual(self.req("DELETE", "/api/agents/atlas")[1], {"deleted": True})
        self.assertEqual(self.req("DELETE", "/api/agents/atlas-2")[1], {"deleted": True})
        _, blue, _ = self.req("POST", "/api/agents", {"id": "blue", "name": "Bluey"})       # edit a built-in = your copy
        self.assertTrue(blue["stock"] and not blue["builtin"])
        self.req("DELETE", "/api/agents/blue")                                             # reset to the original
        self.assertEqual(next(a for a in self.req("GET", "/api/agents")[1] if a["id"] == "blue")["name"], "Blue")

    def test_chat_with_an_agent_and_an_approval(self):
        (self.cfg.workspace / "demo.txt").write_text("old", encoding="utf-8")   # the demo overwrites it: asks first
        q = self.app.bus.subscribe(self.app.bus.publish("mark")["id"])
        status, body, _ = self.req("POST", "/api/chat", {"message": "demo", "agent": "green"})
        self.assertEqual(status, 202)
        try:
            while (e := q.get(timeout=10))["type"] != "approval_request":
                pass
        finally:
            self.app.bus.unsubscribe(q)
        self.assertEqual((e["tool"], e["agent"]), ("write_file", "green"))
        self.assertEqual(self.req("POST", "/api/approve", {"request_id": e["request_id"], "allow": True})[1], {"ok": True})
        self.assertEqual(self.wait_job("chat", body["job_id"])["type"], "job_done")
        self.assertIn("scripted demo", (self.cfg.workspace / "demo.txt").read_text(encoding="utf-8"))
        self.assertEqual(self.req("POST", "/api/chat", {"message": "demo", "agent": "nobody"})[0], 400)

    def test_setup_validates_model_name(self):
        self.assertEqual(self.req("POST", "/api/setup", {"model": "bad name; rm"})[0], 400)

    def test_chat_job(self):
        status, body, _ = self.req("POST", "/api/chat", {"message": "demo"})
        self.assertEqual(status, 202)
        e = self.wait_job("chat", body["job_id"])
        self.assertEqual(e["type"], "job_done")
        self.assertIn("Demo complete", e["result"]["answer"])

    def test_council_job_and_busy(self):
        status, body, _ = self.req("POST", "/api/council", {"question": "Rust or Go?", "agents": ["blue", "green", "orange"],
                                                             "protocol": "vote", "options": ["Rust", "Go"]})
        self.assertEqual(status, 202, body)
        e = self.wait_job("council", body["job_id"])
        self.assertEqual(e["type"], "job_done", e)
        self.assertIn(e["result"]["tally"]["winner"], {"Rust", "Go", None})
        self.assertTrue(Path(e["result"]["transcript"]).exists())

    def test_bad_council_requests(self):
        self.assertEqual(self.req("POST", "/api/council", {"question": "", "agents": ["blue"]})[0], 400)
        self.assertEqual(self.req("POST", "/api/council", {"question": "q", "agents": ["nobody"]})[0], 400)
        self.assertEqual(self.req("POST", "/api/council", {"question": "q", "agents": ["blue"], "protocol": "x"})[0], 400)


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


if __name__ == "__main__":
    unittest.main()
