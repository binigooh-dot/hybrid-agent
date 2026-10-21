"""[PERSONAS / faces] Procedural SVG faces with expressions - no images, no downloads, no API.

A face is described by a small dict of features (FaceSpec). render_face()
draws it as an SVG string in one of several expressions. The GUI swaps the
expression live while a persona thinks, speaks, agrees or objects.

    render_face({"skin": "#e8b48c", "hair_style": "bun", "glasses": True}, "happy")

Analogy: a paper-doll kit. The kit (FaceSpec) is fixed per persona; the
expression just swaps the eyebrows, eyes and mouth pieces.

Every part has a CSS class (face-eyes, face-mouth, face-brows ...) so the
GUI can animate it (blinking, talking) without re-rendering.
"""
from __future__ import annotations

import hashlib
import html

EXPRESSIONS = ("neutral", "thinking", "speaking", "happy", "concerned", "surprised", "skeptical")
HAIR_STYLES = ("short", "long", "bun", "curly", "spiky", "bald", "bob", "mohawk")
FACE_SHAPES = ("oval", "round", "square")
MOUTH_STYLES = ("default", "wide", "small")

DEFAULT_FACE: dict = {
    "skin": "#e8b48c", "hair": "#3b2a20", "hair_style": "short", "eyes": "#4a3b2c", "shape": "oval",
    "accent": "#5b6ee1", "background": "#e9ecf8", "glasses": False, "beard": False, "earrings": False,
    "freckles": False, "blush": True, "mouth_style": "default",
}

SKIN_TONES = ["#f6d7c3", "#eec1a0", "#e8b48c", "#d39b6e", "#b97a4f", "#8d5a3b", "#6b4029", "#4a2c1d"]
HAIR_COLORS = ["#1f1a17", "#3b2a20", "#6a4630", "#a2703f", "#d9b26f", "#c9c9c9", "#8c2f1b", "#3a4e8c"]
ACCENTS = ["#5b6ee1", "#e1795b", "#2fa37a", "#b05bd6", "#d6a12f", "#2f8fd6", "#d64f6b", "#4f5d75"]


def normalise_face(face: dict | None) -> dict:
    """Fill missing features with defaults and sanitise every value (colours are
    validated so user-edited persona files can't inject markup into the SVG)."""
    f = {**DEFAULT_FACE, **(face or {})}
    for key in ("skin", "hair", "eyes", "accent", "background"):
        v = str(f[key])
        f[key] = v if _is_hex_colour(v) else DEFAULT_FACE[key]
    f["hair_style"] = f["hair_style"] if f["hair_style"] in HAIR_STYLES else "short"
    f["shape"] = f["shape"] if f["shape"] in FACE_SHAPES else "oval"
    f["mouth_style"] = f["mouth_style"] if f["mouth_style"] in MOUTH_STYLES else "default"
    for key in ("glasses", "beard", "earrings", "freckles", "blush"):
        f[key] = bool(f[key])
    return {k: f[k] for k in DEFAULT_FACE}


def random_face(seed: str) -> dict:
    """A deterministic face from any string (e.g. a persona name)."""
    h = hashlib.sha256(seed.encode()).digest()
    return normalise_face({
        "skin": SKIN_TONES[h[0] % len(SKIN_TONES)], "hair": HAIR_COLORS[h[1] % len(HAIR_COLORS)],
        "hair_style": HAIR_STYLES[h[2] % len(HAIR_STYLES)], "shape": FACE_SHAPES[h[3] % len(FACE_SHAPES)],
        "accent": ACCENTS[h[4] % len(ACCENTS)], "glasses": h[5] % 4 == 0, "beard": h[6] % 5 == 0,
        "freckles": h[7] % 4 == 0, "earrings": h[8] % 4 == 0,
        "eyes": ["#4a3b2c", "#2f5d8a", "#3d7a4a", "#5a4a8a"][h[9] % 4],
    })


def _is_hex_colour(v: str) -> bool:
    return len(v) in (4, 7) and v.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in v[1:])


def _shade(hex_colour: str, factor: float) -> str:
    """Darken (<1) or lighten (>1) a #rrggbb colour."""
    c = hex_colour.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    rgb = [int(c[i:i + 2], 16) for i in (0, 2, 4)]
    rgb = [max(0, min(255, round(v * factor if factor < 1 else v + (255 - v) * (factor - 1)))) for v in rgb]
    return "#" + "".join(f"{v:02x}" for v in rgb)


# --------------------------------------------------------------------- parts
def _head(f: dict) -> str:
    skin, dark = f["skin"], _shade(f["skin"], 0.85)
    shape = {"oval": '<ellipse cx="100" cy="104" rx="52" ry="62"',
             "round": '<circle cx="100" cy="106" r="58"',
             "square": '<rect x="48" y="46" width="104" height="120" rx="34"'}[f["shape"]]
    ears = (f'<ellipse cx="47" cy="110" rx="9" ry="14" fill="{dark}"/>'
            f'<ellipse cx="153" cy="110" rx="9" ry="14" fill="{dark}"/>')
    rings = ""
    if f["earrings"]:
        rings = (f'<circle cx="46" cy="128" r="4" fill="none" stroke="{f["accent"]}" stroke-width="2.5"/>'
                 f'<circle cx="154" cy="128" r="4" fill="none" stroke="{f["accent"]}" stroke-width="2.5"/>')
    neck = f'<rect x="84" y="150" width="32" height="26" fill="{dark}"/>'
    body = (f'<path d="M30 200 Q34 166 100 162 Q166 166 170 200 Z" fill="{f["accent"]}"/>'
            f'<path d="M84 163 L100 182 L116 163" fill="none" stroke="{_shade(f["accent"], 0.7)}" stroke-width="3"/>')
    return (f'<g class="face-body">{body}{neck}</g><g class="face-head">{ears}{rings}'
            f'{shape} fill="{skin}"/></g>')


def _hair_back(f: dict) -> str:
    h = f["hair"]
    if f["hair_style"] == "long":
        return f'<path d="M44 96 Q40 182 70 176 L130 176 Q160 182 156 96 Z" fill="{_shade(h, 0.85)}"/>'
    if f["hair_style"] == "bob":
        return f'<path d="M42 92 Q38 150 60 152 L140 152 Q162 150 158 92 Z" fill="{_shade(h, 0.85)}"/>'
    return ""


def _hair_front(f: dict) -> str:
    h, style = f["hair"], f["hair_style"]
    if style == "bald":
        return f'<path d="M62 62 Q100 40 138 62" fill="none" stroke="{_shade(f["skin"], 1.15)}" stroke-width="6" opacity=".6"/>'
    if style == "short":
        return f'<path d="M46 98 Q44 44 100 40 Q156 44 154 98 Q150 66 118 62 Q96 74 66 64 Q50 74 46 98 Z" fill="{h}"/>'
    if style in ("long", "bob"):
        return f'<path d="M44 104 Q40 40 100 38 Q160 40 156 104 Q150 62 100 58 Q60 60 52 100 Z" fill="{h}"/>'
    if style == "bun":
        return (f'<circle cx="100" cy="30" r="20" fill="{h}"/>'
                f'<path d="M46 96 Q46 44 100 42 Q154 44 154 96 Q146 62 100 60 Q54 62 46 96 Z" fill="{h}"/>')
    if style == "curly":
        curls = "".join(f'<circle cx="{x}" cy="{y}" r="15" fill="{h}"/>' for x, y in
                        [(56, 74), (70, 54), (90, 44), (110, 44), (130, 54), (144, 74), (52, 96), (148, 96)])
        return curls
    if style == "spiky":
        return (f'<path d="M46 96 L52 50 L66 66 L74 36 L90 58 L100 30 L110 58 L126 36 L134 66 L148 50 '
                f'L154 96 Q140 66 100 64 Q60 66 46 96 Z" fill="{h}"/>')
    if style == "mohawk":
        return f'<path d="M88 74 Q86 30 100 22 Q114 30 112 74 Z" fill="{h}"/>'
    return ""


def _eyes(f: dict, ex: str) -> str:
    c = f["eyes"]
    if ex == "happy":
        return ('<g class="face-eyes"><path d="M70 106 Q80 96 90 106" fill="none" stroke="#2b2b2b" stroke-width="4" '
                'stroke-linecap="round"/><path d="M110 106 Q120 96 130 106" fill="none" stroke="#2b2b2b" '
                'stroke-width="4" stroke-linecap="round"/></g>')
    r = 7.5 if ex == "surprised" else 6
    dx, dy = (4, -4) if ex == "thinking" else (0, 0)
    lid = ""
    if ex == "skeptical":
        lid = f'<path d="M108 93 L134 93 L134 105 Q121 102 108 105 Z" fill="{f["skin"]}"/>'
    if ex == "concerned":
        lid = (f'<path d="M68 99 L92 103 L92 100 L68 96 Z" fill="{f["skin"]}"/>'
               f'<path d="M108 103 L132 99 L132 96 L108 100 Z" fill="{f["skin"]}"/>')
    return (f'<g class="face-eyes"><ellipse cx="80" cy="106" rx="10" ry="{r + 2}" fill="#fff"/>'
            f'<ellipse cx="120" cy="106" rx="10" ry="{r + 2}" fill="#fff"/>'
            f'<circle cx="{80 + dx}" cy="{106 + dy}" r="{r}" fill="{c}"/><circle cx="{120 + dx}" cy="{106 + dy}" r="{r}" fill="{c}"/>'
            f'<circle cx="{78 + dx}" cy="{104 + dy}" r="2" fill="#fff"/><circle cx="{118 + dx}" cy="{104 + dy}" r="2" fill="#fff"/>'
            f'{lid}</g>')


def _brows(f: dict, ex: str) -> str:
    col = _shade(f["hair"], 0.8) if f["hair_style"] != "bald" else _shade(f["skin"], 0.6)
    shapes = {
        "neutral": ("M68 90 Q80 85 92 89", "M108 89 Q120 85 132 90"),
        "speaking": ("M68 89 Q80 84 92 88", "M108 88 Q120 84 132 89"),
        "happy": ("M68 88 Q80 81 92 86", "M108 86 Q120 81 132 88"),
        "thinking": ("M68 88 Q80 84 92 90", "M108 84 Q120 78 132 84"),
        "concerned": ("M68 86 Q80 90 92 94", "M108 94 Q120 90 132 86"),
        "surprised": ("M68 82 Q80 74 92 80", "M108 80 Q120 74 132 82"),
        "skeptical": ("M68 90 Q80 88 92 90", "M108 84 Q120 76 132 82"),
    }[ex]
    return (f'<g class="face-brows" fill="none" stroke="{col}" stroke-width="4.5" stroke-linecap="round">'
            f'<path d="{shapes[0]}"/><path d="{shapes[1]}"/></g>')


def _mouth(f: dict, ex: str) -> str:
    w = {"default": 1.0, "wide": 1.25, "small": 0.75}[f["mouth_style"]]

    def x(v: float) -> float:
        return round(100 + (v - 100) * w, 1)
    lip = _shade(f["skin"], 0.62)
    if ex == "speaking":
        return (f'<g class="face-mouth face-mouth-open"><ellipse cx="100" cy="140" rx="{12 * w}" ry="8" fill="#5a2a2a"/>'
                f'<ellipse cx="100" cy="144" rx="{7 * w}" ry="3" fill="#d9777a"/></g>')
    if ex == "surprised":
        return '<g class="face-mouth"><ellipse cx="100" cy="142" rx="7" ry="9" fill="#5a2a2a"/></g>'
    d = {
        "neutral": f"M{x(86)} 140 Q100 145 {x(114)} 140",
        "thinking": f"M{x(90)} 142 L{x(112)} 139",
        "happy": f"M{x(80)} 136 Q100 156 {x(120)} 136",
        "concerned": f"M{x(86)} 145 Q100 136 {x(114)} 145",
        "skeptical": f"M{x(86)} 142 Q100 142 {x(116)} 136",
    }[ex]
    fill = ' fill="#fff" stroke-linejoin="round"' if ex == "happy" else ' fill="none"'
    return (f'<g class="face-mouth"><path d="{d}"{fill} stroke="{lip}" stroke-width="4" '
            f'stroke-linecap="round"/></g>')


def _extras(f: dict, ex: str) -> str:
    out = []
    if f["blush"] and ex in ("happy", "speaking"):
        out.append('<ellipse cx="66" cy="126" rx="9" ry="5" fill="#ff8a8a" opacity=".35"/>'
                   '<ellipse cx="134" cy="126" rx="9" ry="5" fill="#ff8a8a" opacity=".35"/>')
    if f["freckles"]:
        dots = [(68, 120), (74, 124), (63, 125), (132, 120), (126, 124), (137, 125)]
        out.append("".join(f'<circle cx="{a}" cy="{b}" r="1.4" fill="{_shade(f["skin"], 0.65)}"/>' for a, b in dots))
    out.append(f'<path d="M100 112 Q96 126 100 128" fill="none" stroke="{_shade(f["skin"], 0.75)}" '
               'stroke-width="3" stroke-linecap="round"/>')  # nose
    if f["beard"]:
        out.append(f'<path d="M52 118 Q56 172 100 176 Q144 172 148 118 Q140 150 118 150 Q100 140 82 150 '
                   f'Q60 150 52 118 Z" fill="{f["hair"]}" opacity=".92"/>'
                   # clear a lip area so every expression's mouth stays readable
                   f'<ellipse cx="100" cy="142" rx="17" ry="8" fill="{_shade(f["skin"], 0.9)}"/>')
    if f["glasses"]:
        out.append('<g class="face-glasses" fill="none" stroke="#2b2b2b" stroke-width="3">'
                   '<circle cx="80" cy="106" r="15"/><circle cx="120" cy="106" r="15"/>'
                   '<path d="M95 105 Q100 101 105 105"/><path d="M65 104 L50 100"/><path d="M135 104 L150 100"/></g>')
    if ex == "thinking":
        out.append('<g class="face-bubble" fill="#ffffff" stroke="#9aa3b5" stroke-width="2">'
                   '<circle cx="160" cy="58" r="5"/><circle cx="172" cy="42" r="8"/>'
                   '<circle cx="178" cy="20" r="12"/></g>')
    return "".join(out)


def render_face(face: dict | None, expression: str = "neutral", size: int = 200, title: str = "") -> str:
    """Return an SVG string. Safe to inline in HTML (all inputs sanitised)."""
    f = normalise_face(face)
    ex = expression if expression in EXPRESSIONS else "neutral"
    label = html.escape(title or f"face ({ex})")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="{int(size)}" height="{int(size)}" '
        f'class="persona-face expr-{ex}" role="img" aria-label="{label}"><title>{label}</title>',
        f'<circle cx="100" cy="100" r="100" fill="{f["background"]}"/>',
        '<g>',
        _hair_back(f), _head(f), _extras(f, ex), _eyes(f, ex), _brows(f, ex), _mouth(f, ex), _hair_front(f),
        "</g></svg>",
    ]
    return "".join(parts)


def render_all(face: dict | None, size: int = 200, title: str = "") -> dict[str, str]:
    return {ex: render_face(face, ex, size, title) for ex in EXPRESSIONS}
