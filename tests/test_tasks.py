"""[TESTS / tasks] Task queue + scheduler: schedule maths, persistence, one-at-a-time running, safety."""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from hybrid_agent.tasks import Scheduler, Task, TaskStore, describe, next_run

T0 = dt.datetime(2026, 10, 21, 9, 0)        # a Wednesday


class ScheduleMathTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(next_run({"kind": "interval", "minutes": 30}, T0), T0 + dt.timedelta(minutes=30))
        self.assertEqual(next_run({"kind": "daily", "time": "08:30"}, T0), dt.datetime(2026, 10, 22, 8, 30))
        self.assertEqual(next_run({"kind": "daily", "time": "09:30"}, T0), dt.datetime(2026, 10, 21, 9, 30))
        self.assertEqual(next_run({"kind": "weekly", "time": "08:00", "days": [0]}, T0), dt.datetime(2026, 10, 26, 8, 0))
        self.assertEqual(next_run({"kind": "once", "at": "2026-10-21T10:00"}, T0), dt.datetime(2026, 10, 21, 10, 0))
        self.assertIsNone(next_run({"kind": "once", "at": "2026-10-20T10:00"}, T0))
        self.assertIsNone(next_run({"kind": "manual"}, T0))
        self.assertEqual(describe({"kind": "weekly", "time": "08:00", "days": [0, 3]}), "Mon, Thu at 08:00")

    def test_bad_schedules_and_tasks_are_refused(self):
        for bad in ({"kind": "hourly"}, {"kind": "interval", "minutes": 1}, {"kind": "daily", "time": "25:00"},
                    {"kind": "weekly", "time": "08:00", "days": [9]}, {"kind": "once", "at": "tomorrow"},
                    {"kind": "daily"}):
            with self.assertRaises(ValueError, msg=bad):
                Task(name="x", prompt="y", schedule=bad)
        with self.assertRaises(ValueError):
            Task(name="", prompt="y")
        with self.assertRaises(ValueError):
            Task(name="x", prompt="")
        with self.assertRaises(ValueError):
            Task(name="x", prompt="y", permission="root")
        self.assertEqual(Task(name="drills", kind="diagnose").permission, "safe")    # safe by default


class StoreAndSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.store = TaskStore(self.dir)
        self.started: list[str] = []
        self.busy = False
        self.sched = Scheduler(self.store, lambda t: self.started.append(t.id), lambda: self.busy)

    def test_persists_and_survives_corruption(self):
        t = self.store.upsert({"name": "news", "prompt": "summarise", "schedule": {"kind": "daily", "time": "07:00"}})
        self.assertIsNotNone(t.next_run)
        self.assertEqual(TaskStore(self.dir).get(t.id).name, "news")
        (self.dir / "tasks.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(TaskStore(self.dir).all(), [])
        self.assertTrue(list(self.dir.glob("tasks.json.corrupt-*")))

    def test_runs_one_at_a_time_and_waits_while_busy(self):
        a = self.store.upsert({"name": "a", "prompt": "1"})
        b = self.store.upsert({"name": "b", "prompt": "2"})
        self.sched.enqueue(a.id)
        self.assertFalse(self.sched.enqueue(a.id))          # no duplicates in the queue
        self.sched.enqueue(b.id)
        self.busy = True
        self.assertIsNone(self.sched.tick())                # someone is chatting: wait
        self.busy = False
        self.assertEqual(self.sched.tick(), a.id)
        self.busy = True                                    # a is running now
        self.assertIsNone(self.sched.tick())
        self.busy = False
        self.assertEqual(self.sched.tick(), b.id)
        self.assertEqual(self.started, [a.id, b.id])

    def test_due_tasks_are_queued_and_rescheduled(self):
        t = self.store.upsert({"name": "hourly", "prompt": "x", "schedule": {"kind": "interval", "minutes": 60}})
        self.store.get(t.id).next_run = (dt.datetime.now() - dt.timedelta(minutes=5)).isoformat()   # overdue
        self.assertEqual(self.sched.tick(), t.id)
        nxt = dt.datetime.fromisoformat(self.store.get(t.id).next_run)
        self.assertGreater(nxt, dt.datetime.now() + dt.timedelta(minutes=55))
        self.assertIsNone(self.sched.tick())                # not due again yet

    def test_once_disables_itself_and_pause_holds_the_queue(self):
        t = self.store.upsert({"name": "once", "prompt": "x",
                               "schedule": {"kind": "once", "at": (dt.datetime.now() + dt.timedelta(hours=1)).isoformat(timespec="minutes")}})
        self.store.get(t.id).next_run = dt.datetime.now().isoformat()
        self.sched.set_paused(True)
        self.assertIsNone(self.sched.tick())
        self.assertIn(t.id, self.sched.status()["queue"])
        self.sched.set_paused(False)
        self.assertEqual(self.sched.tick(), t.id)
        self.assertFalse(self.store.get(t.id).enabled)

    def test_run_history_and_results(self):
        t = self.store.upsert({"name": "r", "prompt": "x"})
        run = self.store.record_run(t.id, "ok", dt.datetime.now(), "the answer")
        self.assertEqual(self.store.runs()[0]["preview"], "the answer")
        self.assertIn("the answer", self.store.result_text(run["result"]))
        with self.assertRaises(KeyError):
            self.store.result_text("../tasks.json")         # can't read outside results/
        self.assertEqual(self.store.get(t.id).last_status, "ok")


class SafePermissionTests(unittest.TestCase):
    def test_safe_tasks_get_no_write_or_execute_tools(self):
        """Unattended 'safe' tasks: the scripted backend tries write_file; it must not exist."""
        from hybrid_agent.core.config import Config
        from hybrid_agent.tasks import execute
        tmp = Path(tempfile.mkdtemp())
        cfg = Config(backend="scripted", workspace=tmp / "ws", log_dir=None, persona_dir=tmp / "p")
        cfg.workspace.mkdir()
        execute(Task(name="demo", prompt="demo", permission="safe"), cfg)
        self.assertFalse((cfg.workspace / "demo.txt").exists())
        execute(Task(name="demo", prompt="demo", permission="ask"), cfg, approver=lambda *a: True)
        self.assertTrue((cfg.workspace / "demo.txt").exists())


class TaskApiTests(unittest.TestCase):
    def test_create_run_and_history_over_http(self):
        import threading
        import time
        import urllib.request

        from hybrid_agent.core.config import Config
        from hybrid_agent.gui.server import create_server
        tmp = Path(tempfile.mkdtemp())
        cfg = Config(backend="scripted", workspace=tmp / "ws", log_dir=tmp / "logs", persona_dir=tmp / "p")
        cfg.workspace.mkdir()
        srv, app = create_server(cfg, port=0, state=tmp)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)

        def call(method, path, body=None):
            r = urllib.request.Request(f"http://127.0.0.1:{app.port}{path}", method=method,
                                       data=json.dumps(body).encode() if body is not None else None,
                                       headers={"X-Agent-Token": app.token, "Content-Type": "application/json"})
            with urllib.request.urlopen(r, timeout=10) as resp:
                return json.loads(resp.read())
        t = call("POST", "/api/tasks", {"name": "demo", "prompt": "demo", "schedule": {"kind": "daily", "time": "07:15"}})
        self.assertEqual(call("GET", "/api/tasks")["tasks"][0]["when"], "daily at 07:15")
        self.assertTrue(call("POST", "/api/tasks/run", {"id": t["id"]})["queued"])
        app.scheduler.tick()
        for _ in range(100):
            runs = call("GET", "/api/tasks")["runs"]
            if runs:
                break
            time.sleep(0.1)
        self.assertEqual(runs[0]["status"], "ok")
        self.assertIn("Demo complete", call("GET", f"/api/tasks/result/{runs[0]['result']}")["text"])
        self.assertTrue(call("DELETE", f"/api/tasks/{t['id']}")["deleted"])


if __name__ == "__main__":
    unittest.main()
