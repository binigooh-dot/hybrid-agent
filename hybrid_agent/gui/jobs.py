"""[GUI / jobs] Event bus, approval broker and background jobs for the web GUI.

Analogy: a TV studio control room.
  EventBus        the live feed - everything agents do is broadcast to every
                  open browser tab (Server-Sent Events), and the last few
                  hundred events are kept so a reconnecting tab catches up.
  ApprovalBroker  the producer's headset - when an agent wants to do something
                  risky, it asks; the request appears in the browser and the
                  agent waits for Allow/Deny. No answer within the time limit = Deny.
  JobManager      the floor manager - runs ONE job at a time (chat turn,
                  council session, or diagnostics) in a background thread and
                  can stop it.
"""
from __future__ import annotations

import itertools
import queue
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..core.errors import AgentCancelled, BackendUnavailable
from ..security.redact import redact_obj


class EventBus:
    def __init__(self, history: int = 500):
        self._lock = threading.Lock()
        self._subs: list[queue.Queue] = []
        self._history: list[dict] = []
        self._max = history
        self._ids = itertools.count(1)

    def publish(self, type_: str, **data: Any) -> dict:
        event = {"id": next(self._ids), "type": type_, "time": time.time(), **redact_obj(data)}
        with self._lock:
            self._history.append(event)
            del self._history[:-self._max]
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:  # a stalled browser tab must never block the agents
                pass
        return event

    def subscribe(self, after_id: int = 0) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=2000)
        with self._lock:
            for e in self._history:
                if e["id"] > after_id:
                    q.put_nowait(e)
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)


@dataclass
class _Pending:
    kind: str
    event: threading.Event = field(default_factory=threading.Event)
    answer: Any = None


class ApprovalBroker:
    """Turns the GUI into the y/N prompt for risky tools (and for ask_user)."""

    def __init__(self, bus: EventBus, timeout: float = 180, auto_approve: bool = False):
        self.bus = bus
        self.timeout = timeout
        self.auto_approve = auto_approve
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.Lock()
        self._ids = itertools.count(1)

    def _ask(self, kind: str, payload: dict, default: Any) -> Any:
        rid = f"{kind}-{next(self._ids)}"
        p = _Pending(kind)
        with self._lock:
            self._pending[rid] = p
        self.bus.publish(kind, request_id=rid, timeout=self.timeout, **payload)
        answered = p.event.wait(self.timeout)
        with self._lock:
            self._pending.pop(rid, None)
        if not answered:
            self.bus.publish("request_expired", request_id=rid)
            return default
        return p.answer

    def approver(self, agent_name: str = "agent") -> Callable[[str, dict, str], bool]:
        def approve(tool: str, args: dict, reason: str) -> bool:
            if self.auto_approve:
                return True
            return bool(self._ask("approval_request", {"agent": agent_name, "tool": tool, "args": args,
                                                       "reason": reason}, False))
        return approve

    def asker(self, agent_name: str = "agent") -> Callable[[str], str]:
        def ask(question: str) -> str:
            ans = self._ask("question", {"agent": agent_name, "question": question}, None)
            return ans or "(The user did not answer. Make a reasonable assumption and state it.)"
        return ask

    def answer(self, request_id: str, value: Any) -> bool:
        with self._lock:
            p = self._pending.get(request_id)
        if not p:
            return False
        p.answer = value
        p.event.set()
        return True

    def cancel_all(self) -> None:
        with self._lock:
            pending = list(self._pending.values())
        for p in pending:
            p.answer = None
            p.event.set()


class JobBusy(RuntimeError):
    pass


class JobManager:
    """Runs one background job at a time and publishes its lifecycle events."""

    def __init__(self, bus: EventBus, broker: ApprovalBroker):
        self.bus = bus
        self.broker = broker
        self._lock = threading.Lock()
        self.current: dict | None = None
        self._ids = itertools.count(1)

    def start(self, kind: str, fn: Callable[[], Any], cancel: Callable[[], None] | None = None) -> str:
        with self._lock:
            if self.current:
                raise JobBusy(f"a {self.current['kind']} job is already running")
            job_id = f"{kind}-{next(self._ids)}"
            self.current = {"id": job_id, "kind": kind, "cancel": cancel, "started": time.time()}
        self.bus.publish("job_start", job_id=job_id, kind=kind)

        def run():
            final: tuple[str, dict]
            try:
                final = ("job_done", {"result": fn()})
            except AgentCancelled:
                final = ("job_cancelled", {})
            except BackendUnavailable as e:
                final = ("job_error", {"error": f"Model unavailable: {e}",
                                       "hint": "Run the Safety tab's doctor check."})
            except Exception as e:  # noqa: BLE001 - deliberate boundary: report every failure to the GUI
                final = ("job_error", {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=4)})
            # Mark idle BEFORE announcing the end, so a client reacting instantly
            # to "done" can start the next job without hitting "busy".
            with self._lock:
                self.current = None
            self.bus.publish(final[0], job_id=job_id, kind=kind, **final[1])
        threading.Thread(target=run, daemon=True, name=job_id).start()
        return job_id

    def stop(self) -> bool:
        with self._lock:
            job = self.current
        if not job:
            return False
        self.broker.cancel_all()  # unblock anything waiting for an answer
        if job["cancel"]:
            job["cancel"]()
        self.bus.publish("job_stopping", job_id=job["id"])
        return True

    def status(self) -> dict | None:
        with self._lock:
            return None if not self.current else {k: v for k, v in self.current.items() if k != "cancel"}
