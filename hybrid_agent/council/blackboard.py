"""[COUNCIL / blackboard] A thread-safe shared board that council members post to and read.

Analogy: the whiteboard in the meeting room. Members' private notes (their
own conversation histories) stay private; the board is what they choose to
share. The council also posts each round's positions here automatically.
"""
from __future__ import annotations

import threading
import time


class Blackboard:
    def __init__(self):
        self._lock = threading.Lock()
        self._entries: list[dict] = []

    def post(self, author: str, content: str, topic: str = "note") -> dict:
        with self._lock:
            entry = {"id": len(self._entries) + 1, "author": author, "topic": topic,
                     "content": content, "time": time.strftime("%H:%M:%S")}
            self._entries.append(entry)
            return entry

    def entries(self, topic: str | None = None, last: int | None = None) -> list[dict]:
        with self._lock:
            items = [e for e in self._entries if topic is None or e["topic"] == topic]
        return items[-last:] if last else items

    def render(self, topic: str | None = None, last: int | None = None, max_chars: int = 12000) -> str:
        items = self.entries(topic, last)
        if not items:
            return "(the board is empty)"
        text = "\n\n".join(f"#{e['id']} [{e['topic']}] {e['author']} @ {e['time']}:\n{e['content']}"
                           for e in items)
        return text if len(text) <= max_chars else "...(older posts omitted)\n" + text[-max_chars:]

    def __len__(self) -> int:
        return len(self._entries)
