"""[AGENTS / store] Your agents: a name, a smiley face and which model they use. Nothing else.

    {"id": "blue", "name": "Blue", "face": {"top": "none", "eyes": "o", "mouth": "grin", "color": "#4f7cff"},
     "model": "default"}

model: "default" (whatever the app uses), "local:<model>" (e.g. local:qwen2.5:7b) or "claude".

Three agents exist out of the box (Blue, Green, Orange). Yours are JSON files in the agents folder
(home/agents in the desktop app); one with the same id replaces a built-in one.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .faces import face_for, normalise_face

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_MODEL = re.compile(r"^(default|scripted|claude(:[\w.:-]+)?|local(:[\w./:-]+)?)$")
BUILTIN = [("blue", "Blue"), ("green", "Green"), ("orange", "Orange")]


@dataclass
class AgentProfile:
    id: str
    name: str = ""
    face: dict = field(default_factory=dict)
    model: str = "default"
    builtin: bool = False

    def __post_init__(self):
        if not _ID.match(self.id):
            raise ValueError(f"agent id '{self.id}' must be 1-40 characters: a-z, 0-9, '-' or '_'")
        if not _MODEL.match(str(self.model)):
            raise ValueError(f"agent {self.id}: model must be 'default', 'claude' or 'local:<model>'")
        self.name = str(self.name).strip()[:40] or self.id.capitalize()
        self.face = normalise_face(self.face)

    @classmethod
    def from_dict(cls, d: dict, builtin: bool = False) -> "AgentProfile":
        """Lenient: unknown keys (e.g. from older persona files) are ignored."""
        known = {k: d[k] for k in ("id", "name", "face", "model") if k in d}
        if "model" not in known and isinstance(d.get("backend"), str):     # pre-1.2 persona files
            known["model"] = d["backend"]
        return cls(**known, builtin=builtin)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("builtin")
        return d


def builtin_agents() -> dict[str, AgentProfile]:
    return {aid: AgentProfile(aid, name, face_for(i), builtin=True) for i, (aid, name) in enumerate(BUILTIN)}


def load_agents(folder: Path | None = None) -> dict[str, AgentProfile]:
    """Built-in agents, then yours (a file with the same id replaces a built-in one).
    A broken file is skipped rather than stopping the app."""
    agents = builtin_agents()
    if folder and Path(folder).is_dir():
        for f in sorted(Path(folder).glob("*.json")):
            try:
                a = AgentProfile.from_dict(json.loads(f.read_text(encoding="utf-8")))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            agents[a.id] = a
    return agents


def save_agent(agent: AgentProfile, folder: Path) -> Path:
    """Atomic write. Ids are validated, so the file name can't escape the folder."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{agent.id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(agent.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def delete_agent(agent_id: str, folder: Path) -> bool:
    if not _ID.match(agent_id):
        raise ValueError("bad agent id")
    path = Path(folder) / f"{agent_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def new_agent_id(existing: dict[str, AgentProfile], name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "agent"
    aid, n = base, 2
    while aid in existing:
        aid, n = f"{base}-{n}", n + 1
    return aid
