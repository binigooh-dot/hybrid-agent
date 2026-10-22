"""[TASKS / store] Tasks, schedules and run history, saved as plain JSON in the home folder.

A task is a job for the agents: an agent prompt, a council question, or the safety drills.

    schedule kinds        meaning                           example
    ------------------    ------------------------------    -----------------------------
    {"kind": "manual"}    only when you press Run / queue
    {"kind": "once", "at": "2026-10-22T09:00"}               a single future run
    {"kind": "interval", "minutes": 60}                      every hour
    {"kind": "daily", "time": "08:30"}                       every day at 08:30 (local time)
    {"kind": "weekly", "time": "08:30", "days": [0, 3]}      Mon + Thu (0 = Monday)

Files (home/tasks/):  tasks.json  (the task list)   runs.jsonl  (one line per finished run)
                      results/<task>-<time>.md      (each run's full answer)

Permission ("permission"):
  "safe" (default)  read + network tools only: it can look things up and report, never write or run
                    anything. Right for unattended runs.
  "ask"             normal tools; risky ones wait for your click in the GUI. Nobody there = Deny.

Analogy: a kitchen order rail. Tickets (tasks) are clipped on; the cook (scheduler)
takes one at a time when the stove (the model) is free; finished plates are logged.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

KINDS = ("agent", "council", "diagnose")
PERMISSIONS = ("safe", "ask")
SCHEDULES = ("manual", "once", "interval", "daily", "weekly")
MAX_RUNS_KEPT = 2000


def _now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def _hhmm(s: str) -> tuple[int, int]:
    h, m = (int(x) for x in str(s).split(":", 1))
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError
    return h, m


def validate_schedule(s: dict | None) -> dict:
    s = dict(s or {"kind": "manual"})
    kind = s.get("kind", "manual")
    if kind not in SCHEDULES:
        raise ValueError(f"schedule kind must be one of {', '.join(SCHEDULES)}")
    try:
        if kind == "once":
            dt.datetime.fromisoformat(str(s["at"]))
        elif kind == "interval":
            s["minutes"] = int(s["minutes"])
            if not 5 <= s["minutes"] <= 60 * 24 * 31:
                raise ValueError("interval must be between 5 minutes and 31 days")
        elif kind in ("daily", "weekly"):
            _hhmm(s["time"])
            if kind == "weekly":
                s["days"] = sorted({int(d) for d in s.get("days", [])})
                if not s["days"] or any(not 0 <= d <= 6 for d in s["days"]):
                    raise ValueError("weekly needs days 0-6 (0 = Monday)")
    except (KeyError, TypeError) as e:
        raise ValueError(f"schedule {kind!r} is missing {e}") from None
    except ValueError as e:
        raise ValueError(str(e) if str(e) else f"bad {kind} schedule; time is HH:MM, at is YYYY-MM-DDTHH:MM") from None
    return {k: v for k, v in s.items() if k in ("kind", "at", "minutes", "time", "days")}


def next_run(schedule: dict, after: dt.datetime) -> dt.datetime | None:
    """The first time strictly after `after` that the schedule fires (None = never again)."""
    kind = schedule.get("kind")
    if kind == "once":
        at = dt.datetime.fromisoformat(schedule["at"])
        return at if at > after else None
    if kind == "interval":
        return after + dt.timedelta(minutes=schedule["minutes"])
    if kind in ("daily", "weekly"):
        h, m = _hhmm(schedule["time"])
        day = after.replace(hour=h, minute=m, second=0)
        for _ in range(8):
            if day > after and (kind == "daily" or day.weekday() in schedule["days"]):
                return day
            day += dt.timedelta(days=1)
    return None


def describe(schedule: dict) -> str:
    kind = schedule.get("kind")
    days = "Mon Tue Wed Thu Fri Sat Sun".split()
    return {"manual": "on demand", "once": f"once at {str(schedule.get('at', '')).replace('T', ' ')}",
            "interval": f"every {schedule.get('minutes')} min", "daily": f"daily at {schedule.get('time')}",
            "weekly": f"{', '.join(days[d] for d in schedule.get('days', []))} at {schedule.get('time')}"}.get(str(kind), "?")


@dataclass
class Task:
    name: str
    kind: str = "agent"
    prompt: str = ""
    agent: str = ""                    # kind "agent": which of your agents ("" = default)
    agents: list = field(default_factory=list)     # kind "council": the members
    protocol: str = "roundtable"
    profile: str = ""                  # tool profile ("" = automatic)
    permission: str = "safe"
    schedule: dict = field(default_factory=lambda: {"kind": "manual"})
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    created: str = field(default_factory=lambda: _now().isoformat())
    next_run: str | None = None
    last_run: str | None = None
    last_status: str | None = None     # ok | error | cancelled | skipped

    def __post_init__(self):
        self.name = str(self.name).strip()[:80]
        if not self.name:
            raise ValueError("give the task a name")
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        if self.permission not in PERMISSIONS:
            raise ValueError("permission must be 'safe' or 'ask'")
        if self.kind != "diagnose" and not str(self.prompt).strip():
            raise ValueError("give the task a prompt (what should the agents do?)")
        if self.kind == "council" and not self.agents:
            raise ValueError("a council task needs at least one agent")
        self.prompt = str(self.prompt)[:20000]
        self.schedule = validate_schedule(self.schedule)

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        d = {**d}
        d.setdefault("agent", d.pop("persona", ""))          # tasks saved by 1.1 (personas) still load
        d.setdefault("agents", d.pop("personas", []))
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


class TaskStore:
    """Thread-safe task list + run log, written atomically."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        (self.folder / "results").mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._tasks: dict[str, Task] = {}
        f = self.folder / "tasks.json"
        if f.exists():
            try:
                for d in json.loads(f.read_text(encoding="utf-8")):
                    t = Task.from_dict(d)
                    self._tasks[t.id] = t
            except (json.JSONDecodeError, ValueError, TypeError):
                f.replace(f.with_name(f"tasks.json.corrupt-{_now():%Y%m%d-%H%M%S}"))   # keep it, start fresh

    # ------------------------------------------------------------- tasks
    def _save(self) -> None:
        f = self.folder / "tasks.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(t) for t in self._tasks.values()], indent=1), encoding="utf-8")
        tmp.replace(f)

    def all(self) -> list[Task]:
        with self._lock:
            return sorted(self._tasks.values(), key=lambda t: (t.next_run or "9999", t.name))

    def get(self, task_id: str) -> Task:
        with self._lock:
            if task_id not in self._tasks:
                raise KeyError(f"no task {task_id!r}")
            return self._tasks[task_id]

    def upsert(self, data: dict) -> Task:
        with self._lock:
            old = self._tasks.get(str(data.get("id", "")))
            base = asdict(old) if old else {}
            keep = {k: base[k] for k in ("id", "created", "last_run", "last_status") if k in base}
            t = Task.from_dict({**base, **data, **keep})
            t.next_run = self._first_run(t)
            self._tasks[t.id] = t
            self._save()
            return t

    @staticmethod
    def _first_run(t: Task) -> str | None:
        if not t.enabled or t.schedule["kind"] == "manual":
            return None
        nxt = next_run(t.schedule, _now())
        return nxt.isoformat() if nxt else None

    def delete(self, task_id: str) -> bool:
        with self._lock:
            gone = self._tasks.pop(task_id, None) is not None
            self._save()
            return gone

    def due(self, now: dt.datetime | None = None) -> list[Task]:
        """Enabled tasks whose next_run has arrived (including ones missed while the app was closed)."""
        now = now or dt.datetime.now()          # full precision: a task due at 09:00:00.4 is due at 09:00:00.5
        with self._lock:
            return [t for t in self._tasks.values()
                    if t.enabled and t.next_run and dt.datetime.fromisoformat(t.next_run) <= now]

    def mark_started(self, task_id: str, now: dt.datetime | None = None) -> None:
        """Advance the schedule as soon as a run starts, so it can't be queued twice."""
        now = now or _now()
        with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return
            nxt = next_run(t.schedule, now) if t.schedule["kind"] not in ("manual", "once") else None
            t.next_run = nxt.isoformat() if nxt else None
            if t.schedule["kind"] == "once":
                t.enabled = False
            self._save()

    # ------------------------------------------------------------- runs
    def record_run(self, task_id: str, status: str, started: dt.datetime, text: str, detail: str = "") -> dict:
        with self._lock:
            t = self._tasks.get(task_id)
            name = t.name if t else task_id
            result = self.folder / "results" / f"{task_id}-{started:%Y%m%d-%H%M%S}.md"
            result.write_text(f"# {name}\n\n{started:%Y-%m-%d %H:%M} · {status}\n\n{text}\n", encoding="utf-8")
            run = {"task": task_id, "name": name, "status": status, "started": started.isoformat(),
                   "seconds": round((_now() - started).total_seconds(), 1), "preview": text[:400],
                   "detail": detail[:400], "result": result.name}
            with (self.folder / "runs.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(run) + "\n")
            if t:
                t.last_run, t.last_status = started.isoformat(), status
                self._save()
            self._trim_runs()
            return run

    def _trim_runs(self) -> None:
        f = self.folder / "runs.jsonl"
        lines = f.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_RUNS_KEPT * 1.2:
            f.write_text("\n".join(lines[-MAX_RUNS_KEPT:]) + "\n", encoding="utf-8")

    def runs(self, limit: int = 50, task_id: str = "") -> list[dict]:
        f = self.folder / "runs.jsonl"
        if not f.exists():
            return []
        out = []
        for line in reversed(f.read_text(encoding="utf-8").splitlines()):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not task_id or r.get("task") == task_id:
                out.append(r)
                if len(out) >= limit:
                    break
        return out

    def result_text(self, name: str) -> str:
        f = (self.folder / "results" / name).resolve()
        if f.parent != (self.folder / "results").resolve() or not f.is_file():
            raise KeyError("no such result")
        return f.read_text(encoding="utf-8")
