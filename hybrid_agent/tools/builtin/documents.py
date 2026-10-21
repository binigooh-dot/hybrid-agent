"""[TOOLS / documents] Local document search ("RAG") with no embeddings model and no API.

Tools: index_documents, search_documents

How it works: text files are split into overlapping chunks, and chunks are
ranked with BM25 - the classic search-engine scoring formula (it's what
Elasticsearch/Lucene use by default). It rewards chunks that contain the
query's rarer words, several times, in a short passage.

Analogy: it's the index at the back of a textbook. Building it once
(index_documents) lets the agent jump straight to the right pages later
(search_documents) instead of re-reading every file - which matters a lot
when a local model only has ~8k tokens of context.

Index stored at <workspace>/.agent/doc_index.json.
"""
from __future__ import annotations

import fnmatch
import json
import math
import os
import re
import time
from collections import Counter

from ...security.guards import resolve_in_workspace
from ..registry import FILE_LOCK, S, ToolContext, ToolError, ToolRegistry
from .files import is_binary, walk_files

CATEGORY = "documents"
TEXT_EXT = {".txt", ".md", ".rst", ".py", ".js", ".ts", ".html", ".css", ".json", ".csv", ".yaml",
            ".yml", ".toml", ".ini", ".cfg", ".java", ".go", ".rs", ".c", ".h", ".cpp", ".sh", ".sql",
            ".xml", ".tex", ".org", ".log"}
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [w for w in _TOKEN.findall(text.lower()) if len(w) > 1]


def chunk_text(text: str, size: int = 1200, overlap: int = 200) -> list[tuple[int, str]]:
    """Split into ~size-char chunks on line boundaries -> [(start_line, chunk)]."""
    lines = text.splitlines()
    chunks, buf, start, length = [], [], 1, 0
    for i, line in enumerate(lines, 1):
        buf.append(line)
        length += len(line) + 1
        if length >= size:
            chunks.append((start, "\n".join(buf)))
            keep: list[str] = []
            kept_len = 0
            for ln in reversed(buf):  # carry the tail over as overlap
                if kept_len + len(ln) > overlap:
                    break
                keep.insert(0, ln)
                kept_len += len(ln) + 1
            buf, length, start = keep, kept_len, i - len(keep) + 1
    if buf and "".join(buf).strip():
        chunks.append((start, "\n".join(buf)))
    return chunks


def bm25_rank(query: str, docs: list[dict], k1: float = 1.5, b: float = 0.75) -> list[tuple[float, dict]]:
    q = tokenize(query)
    if not q or not docs:
        return []
    n = len(docs)
    avg = sum(d["len"] for d in docs) / n
    df = Counter(t for d in docs for t in set(d["tf"]))
    scored = []
    for d in docs:
        s = 0.0
        for t in q:
            f = d["tf"].get(t, 0)
            if f:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * d["len"] / avg))
        if s > 0:
            scored.append((s, d))
    return sorted(scored, key=lambda x: -x[0])


def _index_path(ctx: ToolContext):
    return ctx.workspace / ".agent" / "doc_index.json"


_CACHE: dict[str, tuple[float, dict]] = {}   # index path -> (mtime, parsed index)


def _load_index(path) -> dict:
    """Parsed index, re-read only when the file has changed (searches are then instant)."""
    mtime = path.stat().st_mtime
    hit = _CACHE.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    _CACHE[str(path)] = (mtime, data)
    return data


def register(reg: ToolRegistry) -> None:
    t = reg.group(CATEGORY)

    @t("index_documents", "Build (or rebuild) the search index over text files in the workspace "
       "so search_documents can find relevant passages fast.",
       S(path="string?|Folder to index, default '.'", glob="string?|Only matching files, e.g. '*.md'"),
       risk="write")
    def index_documents(ctx: ToolContext, path: str = ".", glob: str = "*"):
        root = resolve_in_workspace(ctx.workspace, path)
        ws = ctx.workspace.resolve()
        docs, files = [], 0
        for full in walk_files(root):
            name = os.path.basename(full)
            if not fnmatch.fnmatch(name, glob) or os.path.splitext(name)[1].lower() not in TEXT_EXT:
                continue
            if os.path.getsize(full) > 5_000_000 or is_binary(full):
                continue
            files += 1
            rel = os.path.relpath(full, ws)
            with open(full, errors="replace", encoding="utf-8") as f:
                for line, chunk in chunk_text(f.read()):
                    toks = tokenize(chunk)
                    docs.append({"file": rel, "line": line, "text": chunk, "len": len(toks),
                                 "tf": dict(Counter(toks))})
        with FILE_LOCK:
            p = _index_path(ctx)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"built": time.strftime("%Y-%m-%d %H:%M"), "chunks": docs}), encoding="utf-8")
        return f"Indexed {files} files into {len(docs)} chunks."

    @t("search_documents", "Search the indexed workspace documents for passages relevant to a "
       "question. Run index_documents first (and again after files change).",
       S(query="string", top_k="integer?|Default 5"))
    def search_documents(ctx: ToolContext, query: str, top_k: int = 5):
        p = _index_path(ctx)
        if not p.exists():
            raise ToolError("No index yet - call index_documents first.")
        idx = _load_index(p)
        hits = bm25_rank(query, idx["chunks"])[:top_k]
        if not hits:
            return "No relevant passages found."
        return "\n\n".join(f"### {d['file']} (line {d['line']}, score {s:.2f})\n{d['text'][:1200]}"
                           for s, d in hits)
