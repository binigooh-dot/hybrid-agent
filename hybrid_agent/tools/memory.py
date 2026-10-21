"""Long-term memory: a JSON file the agent can write notes to and search later.

Analogy: the conversation is short-term memory (it's lost on /reset or
restart). This is a notebook in the agent's pocket - it survives restarts and
is shared between Claude and the local model, because it's just a file.

Stored at <workspace>/.agent/memory.json.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .registry import ToolContext, ToolError, ToolRegistry


def _path(ctx: ToolContext) -> Path:
    return ctx.workspace / ".agent" / "memory.json"


def load(ctx: ToolContext) -> dict:
    p = _path(ctx)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def _save(ctx: ToolContext, data: dict) -> None:
    p = _path(ctx)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(p)  # atomic, so a crash can't leave half a file


def register(reg: ToolRegistry) -> None:

    @reg.tool("remember",
              "Save a fact to long-term memory under a short key. Overwrites the key if it exists.",
              {"type": "object", "properties": {
                  "key": {"type": "string"}, "value": {"type": "string"},
                  "tags": {"type": "array", "items": {"type": "string"}}},
               "required": ["key", "value"]})
    def remember(ctx: ToolContext, key: str, value: str, tags: list | None = None):
        data = load(ctx)
        data[key] = {"value": value, "tags": tags or [], "updated": time.strftime("%Y-%m-%d %H:%M")}
        _save(ctx, data)
        return f"Remembered '{key}'."

    @reg.tool("recall",
              "Search long-term memory. Matches the query words against keys, values and tags. "
              "Empty query lists everything.",
              {"type": "object", "properties": {"query": {"type": "string"}}, "required": []})
    def recall(ctx: ToolContext, query: str = ""):
        data = load(ctx)
        words = query.lower().split()
        hits = []
        for k, v in data.items():
            hay = f"{k} {v['value']} {' '.join(v.get('tags', []))}".lower()
            if all(w in hay for w in words):
                hits.append(f"- {k}: {v['value']}  (tags: {', '.join(v.get('tags', [])) or '-'}; {v['updated']})")
        return "\n".join(hits) or "Nothing found in memory."

    @reg.tool("forget", "Delete a key from long-term memory.",
              {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]})
    def forget(ctx: ToolContext, key: str):
        data = load(ctx)
        if key not in data:
            raise ToolError(f"No memory with key '{key}'.")
        del data[key]
        _save(ctx, data)
        return f"Forgot '{key}'."
