"""[COUNCIL / orchestrator] Council: builds the members and runs a deliberation.

    council = Council.from_config("examples/council.example.json", cfg)
    result  = council.deliberate("Should we rewrite X in Rust?", protocol="debate", rounds=2)
    print(result.final_answer)
    result.save(Path("logs"))           # Markdown + JSON transcript

Each member is a full Agent (own backend/model, own tool profile, own
conversation memory for the session). Members share the workspace, the
long-term memory file and a Blackboard. Members can run in parallel threads
(`workers`); note a single Ollama server only runs OLLAMA_NUM_PARALLEL
requests at once, so parallelism helps most with Claude or several servers.

A member that fails (e.g. its model server is down) is recorded as an
error and simply sits that round out; the council continues as long as at
least one member answered.
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..backends import BackendUnavailable, build_backend_from_spec, build_local_backend
from ..backends.router import RouterBackend
from ..core.agent import Agent
from ..core.config import Config
from ..core.errors import AgentCancelled
from ..security.guards import validate_workspace
from ..security.redact import redact
from ..tools import ToolContext, build_registry
from ..tools.registry import Approver, AskUser
from .blackboard import Blackboard
from .member import CouncilMember, MemberSpec
from .protocols import PROTOCOLS
from .roles import get_role

EventHook = Callable[[str, dict], None]

DEFAULT_MEMBERS = [
    {"name": "chair", "role": "chair"},
    {"name": "researcher", "role": "researcher"},
    {"name": "skeptic", "role": "skeptic"},
    {"name": "engineer", "role": "engineer"},
]


class CouncilError(RuntimeError):
    pass


@dataclass
class Contribution:
    member: str
    role: str
    round: int
    kind: str                  # opening | rebuttal | critique | draft | revision | options | synthesis
    content: str
    seconds: float
    error: str | None = None


@dataclass
class CouncilResult:
    question: str
    protocol: str
    final_answer: str
    members: dict[str, str]                 # name -> role
    contributions: list[Contribution]
    tally: dict | None = None
    options: list[str] | None = None
    board: list[dict] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [f"# Council session: {self.protocol}", "", f"**Question:** {self.question}", "",
                 "**Members:** " + ", ".join(f"{n} ({r})" for n, r in self.members.items()), ""]
        if self.options:
            lines += ["**Options:** " + " | ".join(self.options), ""]
        if self.tally:
            lines += [f"**Vote:** {self.tally.get('summary', '')}", ""]
        lines += ["## Final answer", "", self.final_answer, "", "## Transcript", ""]
        for c in self.contributions:
            head = f"### Round {c.round} · {c.kind} · {c.member} ({c.role}) · {c.seconds:.1f}s"
            lines += [head, "", f"_error: {c.error}_" if c.error else c.content, ""]
        if self.board:
            lines += ["## Shared board", ""]
            lines += [f"- #{e['id']} [{e['topic']}] **{e['author']}**: {e['content'][:500]}" for e in self.board]
        lines += ["", f"_tokens: {self.usage} · {self.seconds:.1f}s_"]
        return "\n".join(lines)

    def save(self, directory: Path | None) -> Path | None:
        """Write Markdown + JSON transcripts (secrets redacted). None = logging off."""
        if directory is None:
            return None
        directory.mkdir(parents=True, exist_ok=True)
        stem = directory / f"council-{time.strftime('%Y%m%d-%H%M%S')}-{self.protocol}"
        stem.with_suffix(".md").write_text(redact(self.to_markdown()), encoding="utf-8")
        stem.with_suffix(".json").write_text(redact(json.dumps(self.to_dict(), indent=2, default=str)), encoding="utf-8")
        return stem.with_suffix(".md")


class Session:
    """State for one deliberation; protocols drive it through gather()/ask()."""

    def __init__(self, council: "Council", question: str, options, rounds: int, tally_mode: str):
        self.council = council
        self.question = question
        self.options = options
        self.rounds = max(1, rounds)
        self.tally_mode = tally_mode
        self.members = council.members
        self.roles = {n: m.role for n, m in council.members.items()}
        self.chair_name = council.chair
        self.participants = council.participants
        self.contributions: list[Contribution] = []
        self.round_no = 0
        self._lock = threading.Lock()

    def event(self, event_name: str, /, **data) -> None:
        self.council.on_event("council", {"event": event_name, **data})

    def ask(self, name: str, prompt: str, kind: str, round_no: int) -> str:
        """One member, one contribution. Errors are recorded, not raised
        (except a user Stop, which ends the whole deliberation)."""
        if self.council._cancelled.is_set():
            raise AgentCancelled("council stopped by user")
        self.round_no = max(self.round_no, round_no)
        m = self.members[name]
        self.event("member_start", member=name, kind=kind, round=round_no)
        start = time.monotonic()
        try:
            text, err = m.ask(prompt), None
        except BackendUnavailable as e:
            text, err = "", str(e)
        c = Contribution(name, m.role, round_no, kind, text, time.monotonic() - start, err)
        with self._lock:
            self.contributions.append(c)
        if text and kind in {"opening", "rebuttal", "draft", "revision"}:
            self.council.board.post(name, text[:4000], topic=f"round{round_no}-{kind}")
        self.event("member_done", member=name, kind=kind, round=round_no, seconds=c.seconds,
                   error=err, preview=text[:200], content=text[:20000])
        return text

    def gather(self, prompts: dict[str, str], kind: str, round_no: int) -> dict[str, str]:
        """Ask several members (in parallel if workers > 1). Returns name -> text
        for members that answered."""
        self.event("round_start", round=round_no, kind=kind, members=list(prompts))
        if self.council.workers > 1 and len(prompts) > 1:
            with ThreadPoolExecutor(max_workers=self.council.workers) as pool:
                futs = {n: pool.submit(self.ask, n, p, kind, round_no) for n, p in prompts.items()}
                out = {n: f.result() for n, f in futs.items()}
        else:
            out = {n: self.ask(n, p, kind, round_no) for n, p in prompts.items()}
        answered = {n: t for n, t in out.items() if t}
        if not answered:
            raise CouncilError(f"no council member could answer in round {round_no} "
                               "(are the model servers running? try `doctor`)")
        return answered


class Council:
    def __init__(self, specs: list[MemberSpec], cfg: Config, *, chair: str | None = None,
                 workers: int | None = None, on_event: EventHook | None = None,
                 approver: Approver | None = None, ask_user: AskUser | None = None):
        if not specs:
            raise ValueError("a council needs at least one member")
        names = [s.name for s in specs]
        if len(set(names)) != len(names):
            raise ValueError("council member names must be unique")
        validate_workspace(cfg.workspace)
        self.cfg = cfg
        self.specs = {s.name: s for s in specs}
        self.workers = workers or cfg.council_workers
        self.on_event = on_event or (lambda kind, data: None)
        self.approver = approver
        self.ask_user = ask_user
        self.board = Blackboard()
        # chair: explicit > first member with role "chair" > first member
        self.chair = chair or next((s.name for s in specs if s.role == "chair"), specs[0].name)
        if self.chair not in self.specs:
            raise ValueError(f"chair '{self.chair}' is not a member")
        # the chair only synthesises, unless they're the only member
        self.participants = [s.name for s in specs if s.name != self.chair] or [self.chair]
        self.members: dict[str, CouncilMember] = {}
        self.defaults: dict[str, Any] = {}       # protocol/rounds/... from a config file
        self.personas: dict[str, Any] = {}       # member name -> Persona, when built from personas
        self._cancelled = threading.Event()
        self._build_members()

    # ------------------------------------------------------------ building
    @classmethod
    def from_personas(cls, persona_ids: list[str], cfg: Config, **kw) -> "Council":
        """Build a council from persona ids (presets or files in cfg.persona_dir).
        The first persona with role 'chair' chairs, unless chair= is given."""
        from ..personas import load_personas
        available = load_personas(cfg.persona_dir)
        missing = [p for p in persona_ids if p not in available]
        if missing:
            raise ValueError(f"unknown persona(s): {', '.join(missing)}. Available: {', '.join(available)}")
        council = cls([available[p].to_member_spec() for p in persona_ids], cfg, **kw)
        council.personas = {p: available[p] for p in persona_ids}
        return council

    @classmethod
    def from_config(cls, source: str | Path | dict | None, cfg: Config, **kw) -> "Council":
        """Build from a JSON file / dict (see examples/council.example.json),
        or the default 4-member council when source is None.

        The config may list "members" (role-based), "personas" (persona ids),
        or both - personas join as extra members."""
        if source is None:
            data: dict[str, Any] = {"members": DEFAULT_MEMBERS}
        elif isinstance(source, dict):
            data = source
        else:
            data = json.loads(Path(source).read_text(encoding="utf-8"))
        specs = [MemberSpec.from_dict(m) for m in data.get("members", [])]
        personas = {}
        if data.get("personas"):
            from ..personas import load_personas
            available = load_personas(cfg.persona_dir)
            for pid in data["personas"]:
                if pid not in available:
                    raise ValueError(f"unknown persona '{pid}'. Available: {', '.join(available)}")
                personas[pid] = available[pid]
                specs.append(available[pid].to_member_spec())
        kw.setdefault("chair", data.get("chair"))
        kw.setdefault("workers", data.get("workers"))
        council = cls(specs, cfg, **kw)
        council.personas = personas
        council.defaults = {k: data[k] for k in ("protocol", "rounds", "tally_mode", "options") if k in data}
        return council

    def _build_members(self) -> None:
        for name, spec in self.specs.items():
            backend = build_backend_from_spec(spec.backend, self.cfg, member=name)
            uses_claude = isinstance(backend, RouterBackend)
            extra = {k: v for k, v in (("approver", self.approver), ("ask_user", self.ask_user)) if v}
            ctx = ToolContext.from_config(self.cfg, max_output=min(self.cfg.max_tool_output, 12000),
                                          agent_name=name, blackboard=self.board, **extra,
                                          local_backend=build_local_backend(self.cfg) if uses_claude else None)
            tools = build_registry(ctx, spec.tool_profile() + ",@council", include_delegate=uses_claude,
                                   safe_mode=self.cfg.safe_mode)
            others = [f"{n} ({self.specs[n].role})" for n in self.specs if n != name]
            agent = Agent(backend, tools, system_prompt=spec.system_prompt(others),
                          max_steps=spec.max_steps or min(self.cfg.max_steps, 12),
                          log_dir=self.cfg.log_dir, on_event=self._relay(name), name=f"council-{name}",
                          context_chars=self.cfg.context_chars())
            self.members[name] = CouncilMember(spec, agent)

    def _relay(self, member: str) -> EventHook:
        def hook(kind: str, data: dict) -> None:
            if kind in {"tool_call", "tool_result"}:
                self.on_event(kind, {**data, "agent": member})
        return hook

    # ------------------------------------------------------------- running
    def cancel(self) -> None:
        """Stop the deliberation at the next safe point (thread-safe)."""
        self._cancelled.set()
        for m in self.members.values():
            m.agent.cancel()

    def reset(self) -> None:
        self._cancelled.clear()
        for m in self.members.values():
            m.agent.reset()
        self.board = Blackboard()
        for m in self.members.values():
            m.agent.tools.ctx.blackboard = self.board

    def describe(self) -> str:
        rows = []
        for n, m in self.members.items():
            tag = " [chair]" if n == self.chair else ""
            rows.append(f"- {n}{tag}: {get_role(m.role).title}, model {m.agent.backend.describe()}, "
                        f"{len(m.agent.tools)} tools ({m.spec.tool_profile()})")
        return "\n".join(rows)

    def deliberate(self, question: str, protocol: str | None = None, rounds: int | None = None,
                   options: list[str] | None = None, tally_mode: str | None = None,
                   fresh: bool = True) -> CouncilResult:
        protocol = protocol or self.defaults.get("protocol", "roundtable")
        if protocol not in PROTOCOLS:
            raise ValueError(f"unknown protocol '{protocol}'. Known: {', '.join(PROTOCOLS)}")
        if fresh:
            self.reset()
        s = Session(self, question, options or self.defaults.get("options"),
                    rounds or self.defaults.get("rounds", 2),
                    tally_mode or self.defaults.get("tally_mode", "weighted"))
        start = time.monotonic()
        s.event("start", protocol=protocol, question=question, members=list(self.members))
        final, t = PROTOCOLS[protocol]().run(s)
        usage = {"input_tokens": 0, "output_tokens": 0}
        for m in self.members.values():
            for k in usage:
                usage[k] += m.agent.usage.get(k, 0)
        tally_d = None
        if t:
            tally_d = {"summary": t.summary(), "winner": t.winner, "scores": t.scores,
                       "tie": t.tie, "consensus": t.consensus, "abstentions": t.abstentions}
        result = CouncilResult(
            question=question, protocol=protocol, final_answer=final or "(the chair gave no answer)",
            members={n: m.role for n, m in self.members.items()}, contributions=s.contributions,
            tally=tally_d, options=s.options, board=self.board.entries(), usage=usage,
            seconds=time.monotonic() - start)
        s.event("done", seconds=result.seconds)
        return result
