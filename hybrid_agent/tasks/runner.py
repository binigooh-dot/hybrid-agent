"""[TASKS / runner] Runs tasks: the scheduler loop, and what "running a task" means for each kind.

The scheduler wakes every few seconds, queues every task that is due (or that
you pressed Run on), and starts the next one only when nothing else is running -
the local model can only think about one thing at a time. A task that comes due
while you're chatting simply waits its turn.

Unattended safety: a task with permission "safe" gets read + network tools only
(it can browse Wikipedia, read your workspace and report, never change anything).
"ask" tasks use the normal approval flow; with nobody at the GUI, risky actions
are denied after the usual 3-minute wait.
"""
from __future__ import annotations

import collections
import dataclasses
import logging
import threading
from collections.abc import Callable

from ..core.config import Config
from .store import Task, TaskStore

log = logging.getLogger(__name__)


def _deny(tool: str, args: dict, reason: str) -> bool:
    return False


def execute(task: Task, cfg: Config, approver=None, asker=None, on_event=None, cancel_hook=None) -> str:
    """Run one task to completion and return its answer as text (blocking)."""
    if task.kind == "diagnose":
        from ..diagnostics.runner import run_all
        rep = run_all()
        bad = [d["title"] for d in rep["drills"] if not d["passed"]]
        return (f"{rep['passed']}/{rep['total']} safety drills passed."
                + (f"\nFailed: {', '.join(bad)}" if bad else "\nAll defences held."))
    run_cfg = dataclasses.replace(cfg, safe_mode=cfg.safe_mode or task.permission == "safe", auto_approve=False)
    approve = _deny if task.permission == "safe" else approver
    if task.kind == "council":
        from ..council import Council
        council = Council.from_agents(task.agents, run_cfg, on_event=on_event, approver=approve, ask_user=asker)
        if cancel_hook:
            cancel_hook(council.cancel)
        result = council.deliberate(task.prompt, protocol=task.protocol)
        result.save(cfg.log_dir)
        return result.final_answer
    from ..agents.build import build_agent
    agent = build_agent(run_cfg, task.agent or None, profile=task.profile or ("research" if task.permission == "safe"
                        else "core"), approver=approve, asker=asker, on_event=on_event, name=f"task-{task.id}",
                        extra_prompt="This is a scheduled task running unattended. Work on your own, then give a "
                                     "complete, self-contained answer: it will be saved as the task's result.")
    if cancel_hook:
        cancel_hook(agent.cancel)
    return agent.run(task.prompt)


class Scheduler:
    """Background loop: queue due tasks, start the next one whenever the runner is free.

    start_job(task) must start the task in the background and return quickly; is_busy()
    says whether anything (a task, a chat, a council) is running right now.
    """

    def __init__(self, store: TaskStore, start_job: Callable[[Task], None], is_busy: Callable[[], bool],
                 poll: float = 5.0, on_change: Callable[[], None] | None = None):
        self.store, self.start_job, self.is_busy, self.poll = store, start_job, is_busy, poll
        self.on_change = on_change or (lambda: None)
        self.queue: collections.deque[str] = collections.deque()
        self.paused = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def enqueue(self, task_id: str) -> bool:
        self.store.get(task_id)                       # KeyError if unknown
        with self._lock:
            if task_id in self.queue:
                return False
            self.queue.append(task_id)
        self._wake.set()
        self.on_change()
        return True

    def remove(self, task_id: str) -> None:
        with self._lock:
            if task_id in self.queue:
                self.queue.remove(task_id)
        self.on_change()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self._wake.set()
        self.on_change()

    def tick(self) -> str | None:
        """One scheduler step (also called directly by tests). Returns the task id started, if any."""
        changed = False
        for t in self.store.due():
            with self._lock:
                if t.id not in self.queue:
                    self.queue.append(t.id)
                    changed = True
        started = None
        if not self.paused and not self.is_busy():
            with self._lock:
                task_id = self.queue.popleft() if self.queue else None
            if task_id:
                try:
                    task = self.store.get(task_id)
                except KeyError:
                    task = None
                if task:
                    self.store.mark_started(task.id)
                    try:
                        self.start_job(task)
                        started = task.id
                    except Exception as e:  # noqa: BLE001 - a failed start must not kill the loop
                        log.warning("task %s could not start: %s", task_id, e)
                        with self._lock:
                            self.queue.appendleft(task_id)    # busy after all: try again next tick
                changed = True
        if changed:
            self.on_change()
        return started

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - keep scheduling no matter what
                log.warning("scheduler tick failed: %s", e)
            self._wake.wait(self.poll)
            self._wake.clear()

    def status(self) -> dict:
        with self._lock:
            return {"paused": self.paused, "queue": list(self.queue)}
