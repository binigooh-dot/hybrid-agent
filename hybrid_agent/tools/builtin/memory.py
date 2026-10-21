"""[TOOLS / memory] Long-term memory: a JSON notebook that survives restarts.

Tools: remember, recall, forget

Analogy: the conversation is short-term memory (lost on /reset or restart).
This is a notebook in the agent's pocket - it survives restarts and is shared
by Claude, the local model and every council member, because it's just a file.

Stored at <workspace>/.agent/memory.json. Writes are atomic and guarded by
FILE_LOCK so council members running in parallel threads can't clobber
each other.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..registry import FILE_LOCK, S, ToolContext, ToolError, ToolRegistry

CATEGORY = "memory"


def _path(ctx: ToolContext) -> Path:
    return ctx.workspace / ".agent" / "memory.json"


def load(ctx: ToolContext) -> dict:
    """Read the memory file. A corrupted file is MOVED ASIDE (memory.json.corrupt-<time>)
    rather than silently replaced, so nothing is lost and it can be repaired by hand."""
    p = _path(ctx)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top level is not an object")
        return data
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        with FILE_LOCK:
            if p.exists():
                backup = p.with_name(f"memory.json.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
                p.replace(backup)
        return {}


def _save(ctx: ToolContext, data: dict) -> None:
    p = _path(ctx)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)  # atomic, so a crash can't leave half a file


def register(reg: ToolRegistry) -> None:
    t = reg.group(CATEGORY)

    @t("remember", "Save a fact to long-term memory under a short key. Overwrites the key if it exists.",
       S(key="string", value="string", tags={"type": "array", "items": {"type": "string"}, "optional": True}),
       risk="write")
    def remember(ctx: ToolContext, key: str, value: str, tags: list | None = None):
        with FILE_LOCK:
            data = load(ctx)
            data[key] = {"value": value, "tags": tags or [], "by": ctx.agent_name,
                         "updated": time.strftime("%Y-%m-%d %H:%M")}
            _save(ctx, data)
        return f"Remembered '{key}'."

    @t("recall", "Search long-term memory. Matches the query words against keys, values and tags. "
       "Empty query lists everything.",
       S(query="string?"))
    def recall(ctx: ToolContext, query: str = ""):
        data = load(ctx)
        words = query.lower().split()
        hits = []
        for k, v in data.items():
            if not isinstance(v, dict):
                continue
            hay = f"{k} {v.get('value', '')} {' '.join(v.get('tags', []))}".lower()
            if all(w in hay for w in words):
                hits.append(f"- {k}: {v.get('value', '')}  (tags: {', '.join(v.get('tags', [])) or '-'}; "
                            f"{v.get('by', '?')}, {v.get('updated', '?')})")
        return "\n".join(hits) or "Nothing found in memory."

    @t("forget", "Delete a key from long-term memory.", S(key="string"), risk="write")
    def forget(ctx: ToolContext, key: str):
        with FILE_LOCK:
            data = load(ctx)
            if key not in data:
                raise ToolError(f"No memory with key '{key}'.")
            del data[key]
            _save(ctx, data)
        return f"Forgot '{key}'."
