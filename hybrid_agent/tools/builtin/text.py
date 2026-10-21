"""[TOOLS / text] Analyse and transform text.

Tools: text_stats, regex_find, regex_replace_file, extract_entities, compare_text,
       encode_decode, hash_text, hash_file, generate_id
"""
from __future__ import annotations

import base64
import binascii
import collections
import difflib
import hashlib
import html
import re
import secrets
import string
import urllib.parse
import uuid

from ...security.guards import (
    compile_regex,
    read_text_limited,
    resolve_in_workspace,
    run_regex_isolated,
)
from ..registry import S, ToolContext, ToolError, ToolRegistry

CATEGORY = "text"
STOPWORDS = set("the a an and or of to in on for with is are was were be been it this that as at by "
                "from but not no so if then than i you he she they we our your their its his her".split())

ENTITY_PATTERNS = {
    "urls": r"https?://[^\s<>\"')\]]+",
    "emails": r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
    "phone_numbers": r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)",
    "dates": r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    "numbers": r"(?<![\w.])-?\d+(?:[.,]\d+)?(?![\w.])",
    "hashtags": r"(?<!\w)#\w+",
    "ip_addresses": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
}


def _text_or_file(ctx: ToolContext, text: str | None, path: str | None) -> str:
    if path:
        p = resolve_in_workspace(ctx.workspace, path)
        if not p.is_file():
            raise ToolError(f"No such file: {path}")
        return read_text_limited(p)
    if text is None:
        raise ToolError("Give either 'text' or 'path'.")
    return text


def register(reg: ToolRegistry) -> None:
    t = reg.group(CATEGORY)

    @t("text_stats", "Count characters, words, sentences, lines; estimate reading time and "
       "list the most frequent words. Give text or a file path.",
       S(text="string?", path="string?"))
    def text_stats(ctx: ToolContext, text: str | None = None, path: str | None = None):
        s = _text_or_file(ctx, text, path)
        words = re.findall(r"[A-Za-z']+", s.lower())
        freq = collections.Counter(w for w in words if w not in STOPWORDS and len(w) > 2)
        return {"characters": len(s), "words": len(words), "lines": s.count("\n") + 1,
                "sentences": len(re.findall(r"[.!?]+(?:\s|$)", s)) or (1 if s.strip() else 0),
                "reading_time_min": round(len(words) / 230, 1),
                "approx_tokens": round(len(s) / 4),
                "top_words": freq.most_common(10)}

    @t("regex_find", "Find all matches of a regular expression in text (or a file). "
       "Shows capture groups. Handy for testing a regex before using it.",
       S(pattern="string", text="string?", path="string?", ignore_case="boolean?"))
    def regex_find(ctx: ToolContext, pattern: str, text: str | None = None, path: str | None = None,
                   ignore_case: bool = False):
        s = _text_or_file(ctx, text, path)
        flags = re.I if ignore_case else 0
        rx, risky = compile_regex(pattern, flags)
        if risky:  # killable child process (ReDoS protection)
            found = run_regex_isolated("finditer", {"pattern": pattern, "flags": flags, "text": s, "limit": 200})
        else:
            found = [[m.start(), m.end(), m.group(0)[:200], list(m.groups())]
                     for _, m in zip(range(200), rx.finditer(s), strict=False)]
        out = [f"[{a}:{b}] {g!r}" + (f"  groups={tuple(gs)}" if gs else "") for a, b, g, gs in found]
        return "\n".join(out) or "No matches."

    @t("regex_replace_file", "Regex search-and-replace across one file. Supports \\1 backreferences. "
       "Returns how many replacements were made.",
       S(path="string", pattern="string", replacement="string", count="integer?|Max replacements, 0 = all"),
       risk="write")
    def regex_replace_file(ctx: ToolContext, path: str, pattern: str, replacement: str, count: int = 0):
        p = resolve_in_workspace(ctx.workspace, path)
        if not p.is_file():
            raise ToolError(f"No such file: {path}")
        text = read_text_limited(p)
        rx, risky = compile_regex(pattern)
        try:
            if risky:
                new, n = run_regex_isolated("subn", {"pattern": pattern, "text": text,
                                                     "replacement": replacement, "count": count})
            else:
                new, n = rx.subn(replacement, text, count=count)
        except re.error as e:
            raise ToolError(f"Bad replacement: {e}") from None
        if n:
            p.write_text(new)
        return f"{n} replacement(s) in {path}"

    @t("extract_entities", "Pull URLs, emails, phone numbers, dates, numbers, hashtags and IPs "
       "out of text or a file.",
       S(text="string?", path="string?",
         kinds={"type": "array", "items": {"type": "string", "enum": list(ENTITY_PATTERNS)},
                "description": "Default: all", "optional": True}))
    def extract_entities(ctx: ToolContext, text: str | None = None, path: str | None = None,
                         kinds: list | None = None):
        s = _text_or_file(ctx, text, path)
        out = {}
        for k in kinds or ENTITY_PATTERNS:
            found = list(dict.fromkeys(m.strip() for m in re.findall(ENTITY_PATTERNS[k], s)))
            if found:
                out[k] = found[:100]
        return out or "Nothing found."

    @t("compare_text", "Show the differences between two pieces of text (unified diff) and a similarity %.",
       S(text_a="string", text_b="string"))
    def compare_text(ctx: ToolContext, text_a: str, text_b: str):
        ratio = difflib.SequenceMatcher(None, text_a, text_b).ratio()
        diff = "\n".join(difflib.unified_diff(text_a.splitlines(), text_b.splitlines(), "a", "b", lineterm=""))
        return f"similarity: {ratio:.1%}\n{diff or '(identical)'}"

    @t("encode_decode", "Encode or decode text: base64, url, hex, html entities, rot13.",
       S(text="string",
         codec={"type": "string", "enum": ["base64", "url", "hex", "html", "rot13"]},
         direction={"type": "string", "enum": ["encode", "decode"]}))
    def encode_decode(ctx: ToolContext, text: str, codec: str, direction: str):
        enc = direction == "encode"
        try:
            if codec == "base64":
                return base64.b64encode(text.encode()).decode() if enc else base64.b64decode(text).decode(errors="replace")
            if codec == "url":
                return urllib.parse.quote(text) if enc else urllib.parse.unquote(text)
            if codec == "hex":
                return text.encode().hex() if enc else bytes.fromhex(text).decode(errors="replace")
            if codec == "html":
                return html.escape(text) if enc else html.unescape(text)
            import codecs
            return codecs.encode(text, "rot13")
        except (binascii.Error, ValueError) as e:
            raise ToolError(f"Can't {direction} as {codec}: {e}") from None

    algos = {"type": "string", "enum": ["md5", "sha1", "sha256", "sha512"], "optional": True}

    @t("hash_text", "Hash a string (default sha256).", S(text="string", algorithm=algos))
    def hash_text(ctx: ToolContext, text: str, algorithm: str = "sha256"):
        return hashlib.new(algorithm, text.encode()).hexdigest()

    @t("hash_file", "Checksum a workspace file (default sha256) - e.g. to verify a download.",
       S(path="string", algorithm=algos))
    def hash_file(ctx: ToolContext, path: str, algorithm: str = "sha256"):
        p = resolve_in_workspace(ctx.workspace, path)
        if not p.is_file():
            raise ToolError(f"No such file: {path}")
        h = hashlib.new(algorithm)
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return f"{algorithm}  {h.hexdigest()}  {path}"

    @t("generate_id", "Generate random identifiers: uuid, hex token, url-safe token, or a strong password.",
       S(kind={"type": "string", "enum": ["uuid", "hex", "urlsafe", "password"]},
         length="integer?|Length for hex/urlsafe/password, default 16",
         count="integer?|How many, default 1"))
    def generate_id(ctx: ToolContext, kind: str, length: int = 16, count: int = 1):
        length = max(4, min(length, 256))
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"

        def one():
            if kind == "uuid":
                return str(uuid.uuid4())
            if kind == "hex":
                return secrets.token_hex(length)[:length]
            if kind == "urlsafe":
                return secrets.token_urlsafe(length)[:length]
            return "".join(secrets.choice(alphabet) for _ in range(length))
        return "\n".join(one() for _ in range(max(1, min(count, 50))))
