"""[COUNCIL / roles] A council has two jobs: members give their view, the chair sums up.

Agents are generic - no built-in personalities. Different views come from the agents
themselves: different models (an agent's `model`), and each answering independently.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    key: str
    title: str
    instructions: str
    tools: str          # default tool profile, see tools/profiles.py


ROLES: dict[str, Role] = {r.key: r for r in [
    Role("chair", "chair",
         "You chair the council: weigh every member's contribution fairly, name where they agree and "
         "disagree, resolve conflicts with reasons, and give a clear, actionable final answer. Judge the "
         "evidence - don't just average opinions.", "readonly"),
    Role("member", "member", "Give your honest, well-reasoned view. Check facts with your tools when it helps.",
         "core"),
]}


def get_role(key: str) -> Role:
    """Any other role name (from older council files: researcher, skeptic, ...) is treated as a member."""
    return ROLES.get(key, ROLES["member"])
