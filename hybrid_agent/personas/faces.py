"""[PERSONAS / faces] Text faces: tiny, recognisable, animated. No images - 7 lines x 16 columns.

A face is a small dict of parts. render_face() turns it into text and animation()
returns the frames for an expression. Built from Unicode box-drawing and block
characters so outlines are solid lines, not dashes:

   ▄▄▄▄▄▄▄▄▄▄▄         <- hair             speaking: mouth opens  ───  ╶▄╴  ▐█▌
  ╭─────────╮          <- head shape       thinking: eyes glance, thought dots rise  ∙ ° ○
  │  ─   ─  │          <- brows (mood)     neutral : blinks now and then
 ◦│ (●)─(●) │◦         <- eyes, glasses, earrings
  │  ∙ ╯ ∙  │          <- nose, freckles
  │   ╰─╯   │          <- mouth (mood / talking)
  ╰▒▒▒▒▒▒▒▒▒╯          <- chin or beard

The GUI ships one font (JetBrains Mono) whose box-drawing glyphs fill the whole
line, so the outlines join up the same on every computer.

Analogy: a paper-doll kit. Each persona keeps the same kit; expressions only
swap the brows, eyes and mouth. Every part comes from a fixed menu, so a
hand-edited persona file can't inject anything into the GUI or terminal.
"""
from __future__ import annotations

import hashlib
from collections.abc import Collection

EXPRESSIONS = ("neutral", "thinking", "speaking", "happy", "concerned", "surprised", "skeptical")
HAIR = {"flat": "▄▄▄▄▄▄▄▄▄▄▄", "spiky": "╱╲╱╲╱╲╱╲╱╲╱", "wavy": "≈≈≈≈≈≈≈≈≈≈≈", "curly": "○◦○◦○◦○◦○◦○",
        "bun": "    ▄█▄    ", "mohawk": "    ▐█▌    ", "bald": "           "}
# left side, right side, top, chin
SHAPES = {"oval": ("│", "│", "╭─────────╮", "╰─────────╯"), "square": ("│", "│", "┌─────────┐", "└─────────┘"),
          "bold": ("┃", "┃", "┏━━━━━━━━━┓", "┗━━━━━━━━━┛"), "frame": ("║", "║", "╔═════════╗", "╚═════════╝")}
EYES = ("●", "○", "◉", "◕", "■", "•")
NOSES = ("╯", "╰", "▵", "┘", "▿", "∙")
MOUTHS = ("default", "wide", "small")
DEFAULT_FACE: dict = {"hair": "flat", "shape": "oval", "eyes": "●", "glasses": False, "nose": "╯",
                      "mouth": "default", "beard": False, "earrings": False, "freckles": False, "color": "#5b6ee1"}
COLORS = ["#5b6ee1", "#e1795b", "#2fa37a", "#b05bd6", "#d6a12f", "#2f8fd6", "#d64f6b", "#4f5d75"]
# persona files written before v1.1 used plain-ASCII parts: map them to the new set
_LEGACY = {"shape": {"round": "frame"}, "eyes": {"o": "●", "0": "○", "@": "◉", "Q": "◕", "*": "■", ".": "•"},
           "nose": {">": "╯", "<": "╰", "^": "▵", "L": "┘", "v": "▿", "J": "∙"}}

# Unicode ranges in the GUI's bundled font subset (gui/static/fonts/face-mono.woff2). Every face
# character must be inside them, so faces never fall back to another font (checked by `diagnose`).
FONT_RANGES = [(0x20, 0x7E), (0xA0, 0xFF), (0x2013, 0x2014), (0x2018, 0x201D), (0x2022, 0x2022), (0x2026, 0x2026),
               (0x203E, 0x203F), (0x2190, 0x2193), (0x2219, 0x2219), (0x2229, 0x2229), (0x2248, 0x2248),
               (0x2500, 0x25FF), (0x2605, 0x2605), (0x2713, 0x2713), (0x2715, 0x2715)]


def in_font(text: str) -> bool:
    return all(c == "\n" or any(a <= ord(c) <= b for a, b in FONT_RANGES) for c in text)


_BROWS: dict[str, tuple[str, str]] = {"neutral": ("─", "─"), "speaking": ("─", "─"), "happy": ("╭", "╮"),
                                      "thinking": ("─", "▔"), "concerned": ("╱", "╲"), "surprised": ("▔", "▔"),
                                      "skeptical": ("▁", "▔")}
# mouth per style: expression -> text, and the 4 talking frames (the mouth opens wider and wider)
_MOUTHS: dict[str, tuple[dict[str, str], list[str]]] = {
    "default": ({"neutral": "───", "happy": "╰─╯", "concerned": "╭─╮", "surprised": "◯", "skeptical": "──╯",
                 "thinking": "╶─╴"}, ["───", "╶▄╴", "▐█▌", "╶▄╴"]),
    "wide": ({"neutral": "─────", "happy": "╰───╯", "concerned": "╭───╮", "surprised": "◯",
              "skeptical": "────╯", "thinking": "╶───╴"}, ["─────", "╶▄▄▄╴", "▐███▌", "╶▄▄▄╴"]),
    "small": ({"neutral": "─", "happy": "‿", "concerned": "∩", "surprised": "○", "skeptical": "~",
               "thinking": "∙"}, ["─", "◦", "○", "◦"]),
}
_DART = [0, -1, 0, 1]                                   # thinking: eyes glance left / right
_BUBBLE = [("   ", "   "), ("   ", "∙  "), (" ° ", "∙  "), (" °○", "∙  ")]   # thinking: dots rise
_SOUND = ["   ", " ) ", " ))", " ) "]                     # speaking (last 2 columns)


def normalise_face(face: dict | None) -> dict:
    """Fill defaults and keep only values from the fixed menus (old ASCII parts are upgraded)."""
    f = {**DEFAULT_FACE, **(face or {})}
    pick: dict[str, Collection[str]] = {"hair": HAIR, "shape": SHAPES, "eyes": EYES, "nose": NOSES, "mouth": MOUTHS}
    for key, menu in pick.items():
        f[key] = _LEGACY.get(key, {}).get(f[key], f[key]) if isinstance(f[key], str) else f[key]
        if f[key] not in menu:
            f[key] = DEFAULT_FACE[key]
    for key in ("glasses", "beard", "earrings", "freckles"):
        f[key] = bool(f[key])
    c = str(f["color"])
    f["color"] = c if len(c) == 7 and c[0] == "#" and all(x in "0123456789abcdefABCDEF" for x in c[1:]) \
        else DEFAULT_FACE["color"]
    return {k: f[k] for k in DEFAULT_FACE}


def random_face(seed: str) -> dict:
    """A deterministic face from any string (e.g. a persona id)."""
    h = hashlib.sha256(seed.encode()).digest()
    return normalise_face({"hair": list(HAIR)[h[0] % len(HAIR)], "shape": list(SHAPES)[h[1] % len(SHAPES)],
                           "eyes": EYES[h[2] % len(EYES)], "nose": NOSES[h[3] % len(NOSES)],
                           "mouth": MOUTHS[h[4] % 3], "glasses": h[5] % 3 == 0, "beard": h[6] % 4 == 0,
                           "earrings": h[7] % 4 == 0, "freckles": h[8] % 4 == 0, "color": COLORS[h[9] % len(COLORS)]})


def render_face(face: dict | None, expression: str = "neutral", frame: int = 0, blink: bool = False) -> str:
    """One frame as text: 7 lines x 16 columns."""
    f = normalise_face(face)
    ex = expression if expression in EXPRESSIONS else "neutral"
    left, right, top, chin = SHAPES[f["shape"]]

    def row(inner: str, ear: str = " ", extra: str = "  ") -> str:      # 1+1+1+9+1+1+2 = 16 columns
        return f" {ear}{left}{inner.center(9)[:9]}{right}{ear}{extra}"

    e1 = e2 = f["eyes"]
    if blink:
        e1 = e2 = "─"
    elif ex == "happy":
        e1 = e2 = "^"
    elif ex == "surprised":
        e1 = e2 = "◯"
    elif ex == "skeptical":
        e1 = "─"
    elif ex == "thinking":
        e1 = e2 = "◔"
    eyes = (f"({e1})─({e2})" if f["glasses"] else f"{e1}   {e2}").center(9)
    if ex == "thinking":  # glance left / right by moving the eyes one column inside the face
        shift = _DART[frame % 4]
        eyes = eyes[1:] + " " if shift < 0 else " " + eyes[:-1] if shift > 0 else eyes
    b1, b2 = _BROWS[ex]
    moods, talk = _MOUTHS[f["mouth"]]
    mouth = talk[frame % 4] if ex == "speaking" else moods[ex]
    nose = f"∙ {f['nose']} ∙" if f["freckles"] else f["nose"]
    ear = "◦" if f["earrings"] else " "
    bubble = _BUBBLE[frame % 4] if ex == "thinking" else ("   ", "   ")
    sound = _SOUND[frame % 4] if ex == "speaking" else "   "
    beard = chin[0] + "▒" * 9 + chin[-1]
    lines = [
        f"  {HAIR[f['hair']]}{bubble[0]}",
        f"  {top}{bubble[1]}",
        row(f"{b1}   {b2}"),
        row(eyes, ear),
        row(nose),
        row(mouth, " ", sound[1:]),
        f"  {beard if f['beard'] else chin}   ",
    ]
    return "\n".join(line[:16].ljust(16) for line in lines)


def animation(face: dict | None, expression: str) -> list[str]:
    """Frames to cycle for an expression (1 frame = still)."""
    n = 4 if expression in ("speaking", "thinking") else 1
    return [render_face(face, expression, i) for i in range(n)]


def render_all(face: dict | None) -> dict[str, list[str]]:
    """Every expression's frames, plus a 'blink' frame - the whole payload the GUI needs (~2 KB)."""
    out = {ex: animation(face, ex) for ex in EXPRESSIONS}
    out["blink"] = [render_face(face, "neutral", blink=True)]
    return out
