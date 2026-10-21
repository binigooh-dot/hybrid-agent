"""[COUNCIL / ballots] Parse votes out of member replies and tally them.

Members are asked to end vote-style answers with two lines:
    VOTE: <option>
    CONFIDENCE: <0-1 or percent>

Tally modes:
    majority  - one member, one vote
    weighted  - each vote counts  member.weight x confidence
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_VOTE = re.compile(r"^\W*VOTE\W*:\s*(.+?)\s*$", re.I | re.M)
_CONF = re.compile(r"^\W*CONFIDENCE\W*:\s*([0-9]*\.?[0-9]+)\s*(%?)", re.I | re.M)

BALLOT_INSTRUCTIONS = ("End your reply with exactly these two lines:\n"
                       "VOTE: <your choice>\nCONFIDENCE: <a number from 0 to 1>")


@dataclass
class Ballot:
    member: str
    choice: str | None
    confidence: float = 0.5
    weight: float = 1.0


def normalise_choice(raw: str, options: list[str] | None) -> str | None:
    """Map free text to one of the options (exact, then prefix/contains, case-insensitive)."""
    raw = raw.strip().strip("*`'\".").strip()
    if not options:
        return raw or None
    low = raw.lower()
    for o in options:
        if low == o.lower():
            return o
    for o in options:
        if low.startswith(o.lower()) or o.lower() in low:
            return o
    return None


def parse_ballot(member: str, text: str, options: list[str] | None = None, weight: float = 1.0) -> Ballot:
    votes = _VOTE.findall(text or "")
    choice = normalise_choice(votes[-1], options) if votes else None
    conf = 0.5
    m = _CONF.findall(text or "")
    if m:
        val, pct = m[-1]
        conf = float(val) / (100 if pct or float(val) > 1 else 1)
        conf = max(0.0, min(conf, 1.0))
    return Ballot(member, choice, conf, weight)


@dataclass
class Tally:
    scores: dict[str, float] = field(default_factory=dict)
    winner: str | None = None
    tie: bool = False
    consensus: bool = False       # every valid ballot chose the same option
    abstentions: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.scores:
            return "No valid votes."
        ranked = sorted(self.scores.items(), key=lambda kv: -kv[1])
        rows = ", ".join(f"{k}: {v:.2f}" for k, v in ranked)
        status = "consensus" if self.consensus else "tie" if self.tie else "split vote"
        abst = f"; abstained: {', '.join(self.abstentions)}" if self.abstentions else ""
        return f"{status} -> {self.winner or 'undecided'} ({rows}{abst})"


def tally(ballots: list[Ballot], mode: str = "weighted") -> Tally:
    t = Tally()
    for b in ballots:
        if b.choice is None:
            t.abstentions.append(b.member)
            continue
        pts = 1.0 if mode == "majority" else b.weight * b.confidence
        t.scores[b.choice] = t.scores.get(b.choice, 0.0) + pts
    if t.scores:
        best = max(t.scores.values())
        leaders = [k for k, v in t.scores.items() if abs(v - best) < 1e-9]
        t.tie = len(leaders) > 1
        t.winner = None if t.tie else leaders[0]
        t.consensus = len(t.scores) == 1
    return t
