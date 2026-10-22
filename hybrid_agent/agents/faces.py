"""[AGENTS / faces] Plain-ASCII smiley faces with small differences so agents are easy to tell apart.

     ,,,,,          <- top: none / hair / spikes / curl / antenna / bow
   .-----.
  /       \\
 |  o   o  |       <- eyes:  o  O  0  *  @  .
 |  \\___/  |       <- mouth: grin / smile / small
  \\       /
   '-----'

Same smiley, slightly different features and colour - like name tags at a meetup.
Every part comes from a fixed menu, so a hand-edited agent file can't inject anything,
and the faces are printable ASCII only: they look the same in any font, browser or console.

Expressions: neutral (blinks now and then), thinking (eyes glance, thought dots rise),
talking (mouth opens and closes), happy, unsure.
"""
from __future__ import annotations

import hashlib

EXPRESSIONS = ("neutral", "thinking", "talking", "happy", "unsure")
TOPS = {"none": "", "hair": ",,,,,", "spikes": "/\\/\\/\\", "curl": "@", "antenna": "o", "bow": ">o<"}
EYES = ("o", "O", "0", "*", "@", ".")
MOUTHS = {"grin": "\\___/", "smile": "\\_/", "small": "u"}
COLORS = ["#4f7cff", "#2fa37a", "#e0832f", "#b05bd6", "#d64f6b", "#1f9bb3", "#8a7a2a", "#5b6474"]
DEFAULT_FACE: dict = {"top": "none", "eyes": "o", "mouth": "grin", "color": COLORS[0]}

WIDTH, HEIGHT = 16, 7
_TALK = ["{m}", "(o)", "(O)", "(o)"]           # talking: mouth opens and closes
_DART = [0, -1, 0, 1]                          # thinking: eyes glance left / right
_DOTS = [("", ""), ("", "."), (".", "o"), ("o", "O")]   # thinking: dots rise beside the head


def normalise_face(face: dict | None) -> dict:
    """Fill defaults and keep only values from the fixed menus."""
    f = {**DEFAULT_FACE, **(face or {})}
    for key, menu in (("top", TOPS), ("eyes", EYES), ("mouth", MOUTHS)):
        if f[key] not in menu:
            f[key] = DEFAULT_FACE[key]
    c = str(f["color"])
    f["color"] = c if len(c) == 7 and c[0] == "#" and all(x in "0123456789abcdefABCDEF" for x in c[1:]) \
        else DEFAULT_FACE["color"]
    return {k: f[k] for k in DEFAULT_FACE}


def face_for(index: int) -> dict:
    """A distinct face for the n-th agent: each feature cycles at a different rate."""
    tops, mouths = list(TOPS), list(MOUTHS)
    return {"top": tops[index % len(tops)], "eyes": EYES[(index * 2) % len(EYES)],
            "mouth": mouths[index % len(mouths)], "color": COLORS[index % len(COLORS)]}


def random_face(seed: str) -> dict:
    h = hashlib.sha256(seed.encode()).digest()
    return {"top": list(TOPS)[h[0] % len(TOPS)], "eyes": EYES[h[1] % len(EYES)],
            "mouth": list(MOUTHS)[h[2] % len(MOUTHS)], "color": COLORS[h[3] % len(COLORS)]}


def render_face(face: dict | None, expression: str = "neutral", frame: int = 0, blink: bool = False) -> str:
    """One frame: 7 lines x 16 columns of printable ASCII."""
    f = normalise_face(face)
    ex = expression if expression in EXPRESSIONS else "neutral"
    eye = "-" if blink else "^" if ex == "happy" else f["eyes"]
    eyes = f"{eye}   {eye}".center(7)
    if ex == "thinking":                               # glance by moving the eyes one column
        shift = _DART[frame % 4]
        eyes = eyes[1:] + " " if shift < 0 else " " + eyes[:-1] if shift > 0 else eyes
    mouth = MOUTHS[f["mouth"]]
    if ex == "happy":
        mouth = "\\___/"
    elif ex == "unsure":
        mouth = ".-."
    elif ex == "thinking":
        mouth = "-"
    elif ex == "talking":
        mouth = _TALK[frame % 4].format(m=mouth)
    dot_hi, dot_lo = _DOTS[frame % 4] if ex == "thinking" else ("", "")
    sound = (")" if frame % 2 else "))") if ex == "talking" and frame % 4 else ""
    lines = [
        f"    {TOPS[f['top']].center(7)}  {dot_hi}",
        f"    .-----.  {dot_lo}",
        "   /       \\",
        f"  | {eyes} |",
        f"  | {mouth.center(7)} | {sound}",
        "   \\       /",
        "    '-----'",
    ]
    return "\n".join(line.rstrip().ljust(WIDTH)[:WIDTH] for line in lines)


def animation(face: dict | None, expression: str) -> list[str]:
    """Frames to cycle for an expression (1 frame = still)."""
    n = 4 if expression in ("talking", "thinking") else 1
    return [render_face(face, expression, i) for i in range(n)]


def render_all(face: dict | None) -> dict[str, list[str]]:
    """Every expression's frames plus a blink frame: everything the GUI needs (about 1 KB)."""
    out = {ex: animation(face, ex) for ex in EXPRESSIONS}
    out["blink"] = [render_face(face, "neutral", blink=True)]
    return out
