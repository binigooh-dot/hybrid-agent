"""[SECURITY / redact] Scrub secrets from text before it is written to disk or shown in the GUI.

Used for session logs, council transcripts and GUI event streams. Tool results
sent to the MODEL are not altered (the agent may legitimately need to read a
config file), so keep secrets out of the workspace when using a hosted model.
"""
from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "[REDACTED:anthropic-key]"),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}"), "[REDACTED:api-key]"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED:aws-key-id]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}"), "[REDACTED:github-token]"),
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), "[REDACTED:slack-token]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "[REDACTED:google-key]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "[REDACTED:jwt]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "[REDACTED:private-key]"),
    (re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\b(\s*[:=]\s*)(['\"]?)[^\s'\"]{6,}\3"),
     r"\1\2[REDACTED]"),
]


def redact(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    for rx, repl in _PATTERNS:
        text = rx.sub(repl, text)
    return text


def redact_obj(obj):
    """Recursively redact strings inside dicts/lists (for JSON logs)."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    return obj
