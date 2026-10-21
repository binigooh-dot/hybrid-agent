"""[PERSONAS / model] A persona = a named council member with a personality and a face.

    {
      "id": "sage", "name": "Sage", "title": "The Chair", "role": "chair",
      "backend": "default", "tools": null, "weight": 1.0,
      "personality": "Calm and fair ...", "speaking_style": "Measured, uses analogies",
      "greeting": "Let's hear everyone out.",
      "face": {"skin": "#d39b6e", "hair_style": "bun", "glasses": true, ...},
      "image": null
    }

Personas are plain JSON files. Built-in presets live in personas/presets/;
your own go in the folder named by AGENT_PERSONA_DIR (default ./personas).
A user persona with the same id overrides a preset.

`image` is optional: a path (inside the persona folder) or https URL of a
picture to use instead of the drawn face - the groundwork for generated
portraits or animated avatars later.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..council.member import MemberSpec
from ..council.roles import ROLES
from .faces import normalise_face, random_face

PRESET_DIR = Path(__file__).resolve().parent / "presets"
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


@dataclass
class Persona:
    id: str
    name: str
    role: str = "generalist"
    title: str = ""
    personality: str = ""
    speaking_style: str = ""
    greeting: str = ""
    backend: str = "default"
    tools: str | None = None
    weight: float = 1.0
    face: dict = field(default_factory=dict)
    image: str | None = None
    builtin: bool = False

    def __post_init__(self):
        if not _ID.match(self.id):
            raise ValueError(f"persona id '{self.id}' must be 1-40 chars of a-z, 0-9, '-' or '_'")
        if self.role not in ROLES:
            raise ValueError(f"persona {self.id}: unknown role '{self.role}' (known: {', '.join(ROLES)})")
        if not isinstance(self.weight, (int, float)) or not 0 < self.weight <= 10:
            raise ValueError(f"persona {self.id}: weight must be between 0 and 10")
        if self.image and not (self.image.startswith("https://") or _ID.match(Path(self.image).stem or "x")):
            raise ValueError(f"persona {self.id}: image must be an https URL or a file name in the persona folder")
        self.name = str(self.name)[:40] or self.id
        self.face = normalise_face(self.face or random_face(self.id))
        self.title = self.title or ROLES[self.role].title

    # ------------------------------------------------------------- converting
    @classmethod
    def from_dict(cls, d: dict, builtin: bool = False) -> "Persona":
        known = set(cls.__dataclass_fields__) - {"builtin"}
        unknown = set(d) - known - {"_comment"}
        if unknown:
            raise ValueError(f"unknown persona field(s): {', '.join(sorted(unknown))}")
        return cls(**{k: v for k, v in d.items() if k in known}, builtin=builtin)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("builtin")
        return d

    def persona_text(self) -> str:
        """The personality prompt given to the model (role persona + this character)."""
        parts = [ROLES[self.role].persona]
        if self.personality:
            parts.append(f"Your character, {self.name}: {self.personality}")
        if self.speaking_style:
            parts.append(f"Speaking style: {self.speaking_style}. Stay in character, but never let style "
                         "get in the way of being accurate and useful.")
        return "\n\n".join(parts)

    def to_member_spec(self) -> MemberSpec:
        return MemberSpec(name=self.id, role=self.role, backend=self.backend, tools=self.tools,
                          persona=self.persona_text(), weight=float(self.weight))


# ------------------------------------------------------------------- storage
def _load_dir(folder: Path, builtin: bool) -> dict[str, Persona]:
    out: dict[str, Persona] = {}
    if not folder.is_dir():
        return out
    for f in sorted(folder.glob("*.json")):
        try:
            p = Persona.from_dict(json.loads(f.read_text()), builtin=builtin)
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            raise ValueError(f"{f}: {e}") from None
        out[p.id] = p
    return out


def load_presets() -> list[Persona]:
    return list(_load_dir(PRESET_DIR, builtin=True).values())


def load_personas(user_dir: Path | None = None) -> dict[str, Persona]:
    """Presets, overridden by user personas with the same id."""
    personas = _load_dir(PRESET_DIR, builtin=True)
    if user_dir:
        personas.update(_load_dir(Path(user_dir), builtin=False))
    return personas


def save_persona(persona: Persona, user_dir: Path) -> Path:
    """Write a persona to the user folder (atomic). Ids are validated, so the
    file name can never escape the folder."""
    user_dir = Path(user_dir)
    user_dir.mkdir(parents=True, exist_ok=True)
    path = user_dir / f"{persona.id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(persona.to_dict(), indent=2))
    tmp.replace(path)
    return path


def delete_persona(persona_id: str, user_dir: Path) -> bool:
    if not _ID.match(persona_id):
        raise ValueError("bad persona id")
    path = Path(user_dir) / f"{persona_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False
