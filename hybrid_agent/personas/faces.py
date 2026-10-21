"""[PERSONAS / faces] ASCII faces: tiny, recognisable, animated. Pure text, no images.

A face is a small dict of parts. render_face() turns it into 7 lines of text
(16 columns), and animation() returns the frames for an expression:

     /\\/\\/\\/\\/      <- hair            speaking: mouth cycles  ---  (o)  (O)
    .---------.     <- head shape      thinking: eyes dart, thought dots grow
    |  -   -  |     <- brows (mood)    neutral : blinks now and then
   o| [o]-[o] |o    <- eyes, glasses, earrings
    |  . > .  |     <- nose, freckles
    |   ---   |     <- mouth (mood / talking)
    '---------'     <- chin or beard

Analogy: a paper-doll kit. Each persona keeps the same kit; expressions only
swap the brows, eyes and mouth. Every part comes from a fixed menu, so a
hand-edited persona file can't inject anything into the GUI or terminal.
"""
from __future__ import annotations

import hashlib
from collections.abc import Collection

EXPRESSIONS = ("neutral", "thinking", "speaking", "happy", "concerned", "surprised", "skeptical")
HAIR = {"spiky": " /\\/\\/\\/\\/ ", "curly": " @@@@@@@@@ ", "wavy": " ~~~~~~~~~ ", "bun": "   (@@@)   ",
        "mohawk": "    |||    ", "flat": " _________ ", "bald": "           "}
SHAPES = {"oval": ("|", "|", ".---------.", "'---------'"), "round": ("(", ")", " .-------. ", " '-------' "),
          "square": ("[", "]", "+---------+", "+---------+")}
EYES = ("o", "0", "@", "*", "Q", ".")
NOSES = (">", "<", "^", "L", "v", "J")
MOUTHS = ("default", "wide", "small")
BEARD = "\\vvvvvvvvv/"
DEFAULT_FACE: dict = {"hair": "flat", "shape": "oval", "eyes": "o", "glasses": False, "nose": ">",
                      "mouth": "default", "beard": False, "earrings": False, "freckles": False, "color": "#5b6ee1"}
COLORS = ["#5b6ee1", "#e1795b", "#2fa37a", "#b05bd6", "#d6a12f", "#2f8fd6", "#d64f6b", "#4f5d75"]

_BROWS: dict[str, str] = {"neutral": "--", "speaking": "--", "happy": "~~", "thinking": "-~", "concerned": "/\\",
          "surprised": "^^", "skeptical": "-/"}
# mouth per style: expression -> text, and the 4 talking frames
_MOUTHS: dict[str, tuple[dict[str, str], list[str]]] = {
    "default": ({"neutral": "---", "happy": "\\_/", "concerned": "/~\\", "surprised": "O", "skeptical": "--~",
                 "thinking": "-"}, ["---", "(o)", "(O)", "(o)"]),
    "wide": ({"neutral": "-----", "happy": "\\___/", "concerned": "/~~~\\", "surprised": "(O)",
              "skeptical": "---~~", "thinking": "---"}, ["-----", "(_o_)", "( O )", "(_o_)"]),
    "small": ({"neutral": "-", "happy": "u", "concerned": "n", "surprised": "o", "skeptical": "~",
               "thinking": "."}, ["-", "o", "O", "o"]),
}
_DART = [0, -1, 0, 1]                      # thinking: eyes look around
_DOTS = [" .  ", " .. ", " ...", " .. "]   # thinking: thought bubble


def normalise_face(face: dict | None) -> dict:
    """Fill defaults and keep only values from the fixed menus."""
    f = {**DEFAULT_FACE, **(face or {})}
    pick: dict[str, Collection[str]] = {"hair": HAIR, "shape": SHAPES, "eyes": EYES, "nose": NOSES, "mouth": MOUTHS}
    for key, menu in pick.items():
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
    return normalise_face({"hair": list(HAIR)[h[0] % len(HAIR)], "shape": list(SHAPES)[h[1] % 3],
                           "eyes": EYES[h[2] % len(EYES)], "nose": NOSES[h[3] % len(NOSES)],
                           "mouth": MOUTHS[h[4] % 3], "glasses": h[5] % 3 == 0, "beard": h[6] % 4 == 0,
                           "earrings": h[7] % 4 == 0, "freckles": h[8] % 4 == 0, "color": COLORS[h[9] % len(COLORS)]})


def render_face(face: dict | None, expression: str = "neutral", frame: int = 0, blink: bool = False) -> str:
    """One frame as text: 7 lines x 16 columns."""
    f = normalise_face(face)
    ex = expression if expression in EXPRESSIONS else "neutral"
    left, right, top, chin = SHAPES[f["shape"]]

    def row(inner: str) -> str:
        return f" {left}{inner.center(9)[:9]}{right} "

    # eyes (expression and blinking change the glyphs; thinking makes them dart)
    e1 = e2 = f["eyes"]
    if blink:
        e1 = e2 = "-"
    elif ex == "happy":
        e1 = e2 = "^"
    elif ex == "surprised":
        e1 = e2 = "O"
    elif ex == "skeptical":
        e1 = "-"
    eyes = (f"[{e1}]-[{e2}]" if f["glasses"] else f"{e1}   {e2}").center(9)
    if ex == "thinking":  # glance left / right by moving the eyes one column inside the face
        shift = _DART[frame % 4]
        eyes = eyes[1:] + " " if shift < 0 else " " + eyes[:-1] if shift > 0 else eyes
    b1, b2 = _BROWS[ex][0], _BROWS[ex][1]
    brows = f"{b1}   {b2}"
    moods, talk = _MOUTHS[f["mouth"]]
    mouth = talk[frame % 4] if ex == "speaking" else moods[ex]
    nose = f". {f['nose']} ." if f["freckles"] else f["nose"]
    ear = "o" if f["earrings"] else " "
    bubble = _DOTS[frame % 4] if ex == "thinking" else "    "
    sound = (" ))" if frame % 2 else " ) ") if ex == "speaking" else "   "
    lines = [
        f" {HAIR[f['hair']]} " + bubble[:3],
        f" {top} " + bubble[1:],
        row(brows) + "   ",
        f"{ear}{left}{eyes}{right}{ear}" + "   ",
        row(nose) + "   ",
        row(mouth) + sound,
        f" {BEARD if f['beard'] else chin} " + "   ",
    ]
    return "\n".join(line.ljust(16) for line in lines)


def animation(face: dict | None, expression: str) -> list[str]:
    """Frames to cycle for an expression (1 frame = still)."""
    n = 4 if expression in ("speaking", "thinking") else 1
    return [render_face(face, expression, i) for i in range(n)]


def render_all(face: dict | None) -> dict[str, list[str]]:
    """Every expression's frames, plus a 'blink' frame - the whole payload the GUI needs (~2 KB)."""
    out = {ex: animation(face, ex) for ex in EXPRESSIONS}
    out["blink"] = [render_face(face, "neutral", blink=True)]
    return out
