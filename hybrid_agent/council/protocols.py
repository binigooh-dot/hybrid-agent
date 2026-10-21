"""[COUNCIL / protocols] Deliberation procedures - the "rules of order" for a council meeting.

    roundtable  Everyone answers independently (no peeking), then the chair
                synthesises. Cheapest; best for brainstorming and coverage.
                Analogy: sticky notes written in silence, then read aloud.

    debate      Independent opening statements, then N-1 rounds where each
                member sees the others' latest positions and may revise.
                Stops early on consensus (when voting on options). Then
                the chair synthesises. Best for hard questions with a right answer.

    vote        Members choose between explicit options with reasons and a
                confidence; ballots are tallied (weighted or majority). The
                chair breaks ties and writes up the decision. If no options are
                given, the chair first proposes them.

    critique    One author drafts; the others critique; the author revises -
                repeated `rounds` times. Best for producing an artefact
                (a plan, an essay, code) rather than choosing.

Add a protocol: subclass Protocol, implement run(), add it to PROTOCOLS.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .ballots import BALLOT_INSTRUCTIONS, Tally, parse_ballot, tally

if TYPE_CHECKING:
    from .council import Session

MAX_POSITION_CHARS = 2500  # per member, when showing positions to others (protects small contexts)


def format_positions(positions: dict[str, str], roles: dict[str, str], exclude: str | None = None) -> str:
    out = []
    for name, full in positions.items():
        if name == exclude or not full:
            continue
        text = full if len(full) <= MAX_POSITION_CHARS else full[:MAX_POSITION_CHARS] + " ...[shortened]"
        out.append(f"### {name} ({roles.get(name, '?')})\n{text}")
    return "\n\n".join(out) or "(no other positions)"


def options_block(options: list[str] | None) -> str:
    if not options:
        return ""
    return "Options:\n" + "\n".join(f"- {o}" for o in options) + "\n\n" + BALLOT_INSTRUCTIONS


class Protocol:
    name = "base"
    description = ""

    def run(self, s: "Session") -> tuple[str, Tally | None]:
        raise NotImplementedError

    # -- shared steps ---------------------------------------------------
    def opening(self, s: "Session") -> dict[str, str]:
        prompt = (f"Council question:\n{s.question}\n\n"
                  "Give your independent position. Use tools if facts need checking.\n"
                  + options_block(s.options))
        return s.gather({n: prompt for n in s.participants}, kind="opening", round_no=1)

    def vote_tally(self, s: "Session", positions: dict[str, str]) -> Tally | None:
        if not s.options:
            return None
        ballots = [parse_ballot(n, positions[n], s.options, s.members[n].spec.weight)
                   for n in positions if positions[n]]
        return tally(ballots, s.tally_mode)

    def synthesize(self, s: "Session", positions: dict[str, str], t: Tally | None,
                   extra: str = "") -> str:
        prompt = (f"Council question:\n{s.question}\n\n"
                  f"Final positions of the members:\n\n{format_positions(positions, s.roles)}\n\n"
                  + (f"Vote result: {t.summary()}\n\n" if t else "")
                  + extra +
                  "As chair, write the council's final answer with these sections:\n"
                  "1. Answer / decision\n2. Key reasons (where members agreed)\n"
                  "3. Disagreements and how you resolved them\n4. Risks and open questions\n"
                  "5. Overall confidence (low / medium / high)")
        answer = s.ask(s.chair_name, prompt, kind="synthesis", round_no=s.round_no + 1)
        if answer:
            return answer
        # Chair unavailable: return the raw positions rather than nothing.
        s.event("chair_failed", detail="returning unsynthesised positions")
        return ((f"Vote result: {t.summary()}\n\n" if t else "")
                + "(The chair could not synthesise; members' final positions follow.)\n\n"
                + format_positions(positions, s.roles))


class Roundtable(Protocol):
    name = "roundtable"
    description = "independent answers, then the chair synthesises"

    def run(self, s):
        positions = self.opening(s)
        t = self.vote_tally(s, positions)
        return self.synthesize(s, positions, t), t


class Debate(Protocol):
    name = "debate"
    description = "opening statements, then rounds of rebuttal/revision, then synthesis"

    def run(self, s):
        positions = self.opening(s)
        t = self.vote_tally(s, positions)
        for r in range(2, s.rounds + 1):
            if t and t.consensus and not t.abstentions:
                s.event("consensus", round=r - 1, winner=t.winner)
                break
            prompts = {}
            for n in s.participants:
                prompts[n] = (f"Round {r}. Here are the other members' current positions:\n\n"
                              f"{format_positions(positions, s.roles, exclude=n)}\n\n"
                              "Respond to their strongest points. Say what you now agree with, what you "
                              "still dispute and why, then state your (possibly revised) position.\n"
                              + options_block(s.options))
            new = s.gather(prompts, kind="rebuttal", round_no=r)
            positions = {n: new.get(n) or positions.get(n, "") for n in s.participants}
            t = self.vote_tally(s, positions)
        return self.synthesize(s, positions, t), t


class Vote(Protocol):
    name = "vote"
    description = "members vote on options with reasons; tally; chair writes up the decision"

    def run(self, s):
        if not s.options:
            proposal = s.ask(s.chair_name,
                             f"Council question:\n{s.question}\n\nList 2 to 5 distinct options the council "
                             "should vote on, one per line, each starting with '- '. Nothing else.",
                             kind="options", round_no=0)
            s.options = [m.strip() for m in re.findall(r"^\s*[-*\d.)]+\s*(.+)$", proposal, re.M)][:5]
            if len(s.options) < 2:
                s.options = None
                s.event("no_options", detail="chair did not produce options; falling back to roundtable")
                return Roundtable().run(s)
            s.event("options", options=s.options)
        positions = self.opening(s)
        t = self.vote_tally(s, positions)
        extra = ""
        if t and t.tie:
            leaders = [k for k, v in t.scores.items() if v == max(t.scores.values())]
            extra = (f"The vote is TIED between: {', '.join(leaders)}. As chair you must break the tie "
                     "and say which option wins and why.\n\n")
        return self.synthesize(s, positions, t, extra), t


class Critique(Protocol):
    name = "critique"
    description = "an author drafts, the others critique, the author revises (repeat)"

    def run(self, s):
        author = s.participants[0]
        critics = [n for n in s.participants if n != author]
        draft = s.ask(author, f"Council task:\n{s.question}\n\nYou are the author. Produce a complete "
                              "first draft.", kind="draft", round_no=1)
        if not draft:
            from .council import CouncilError
            raise CouncilError(f"the author ({author}) could not produce a draft")
        for r in range(1, s.rounds + 1):
            if not critics:
                break
            prompt = (f"Council task:\n{s.question}\n\nCurrent draft by {author}:\n\n{draft}\n\n"
                      "Critique it from your role's point of view: the most important problems first, "
                      "each with a concrete suggested fix. Say what is good too, briefly.")
            crits = s.gather({c: prompt for c in critics}, kind="critique", round_no=r + 1)
            draft = s.ask(author, "The council's critiques of your draft:\n\n"
                                  f"{format_positions(crits, s.roles)}\n\n"
                                  "Revise the draft. Adopt the good suggestions, briefly say which you "
                                  "rejected and why, then give the full revised version.",
                          kind="revision", round_no=r + 1)
        return draft, None


PROTOCOLS: dict[str, type[Protocol]] = {p.name: p for p in (Roundtable, Debate, Vote, Critique)}
