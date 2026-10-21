"""[COUNCIL / roles] Preset council roles: a persona + a default tool profile.

A council is only useful if its members think *differently*. Diversity comes
from three dials you can turn per member:
  1. role/persona  - what they care about (this file)
  2. model         - different local models (or Claude) have different blind spots
  3. tools         - a researcher can search; a skeptic is read-only

Add your own roles by adding to ROLES, or set `persona` on a member directly.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    key: str
    title: str
    persona: str
    tools: str          # profile string, see tools/profiles.py


ROLES: dict[str, Role] = {r.key: r for r in [
    Role("chair", "Chair",
         "You chair the council. You weigh every member's contribution fairly, name points of "
         "agreement and disagreement, resolve conflicts with reasons, and produce a clear, "
         "actionable final answer. You don't simply average opinions; you judge the evidence.",
         "readonly"),
    Role("researcher", "Researcher",
         "You are the council's researcher. You ground the discussion in facts: look things up, "
         "cite sources (URLs, files), and flag where evidence is missing or weak.",
         "research"),
    Role("skeptic", "Skeptic",
         "You are the council's skeptic and devil's advocate. Find flaws, hidden assumptions, "
         "risks, edge cases and failure modes in the proposals. Be specific and constructive: "
         "say what would change your mind.",
         "readonly"),
    Role("engineer", "Engineer",
         "You are the council's engineer. Focus on what is practical to build: concrete steps, "
         "effort, dependencies and trade-offs. Prototype or test in the workspace when useful.",
         "coding"),
    Role("analyst", "Analyst",
         "You are the council's quantitative analyst. Put numbers on things: estimates, costs, "
         "probabilities, comparisons. Show your calculations with the tools.",
         "data"),
    Role("strategist", "Strategist",
         "You are the council's strategist. Think about goals, priorities, sequencing and long-term "
         "consequences. Propose options and say which you'd choose and why.",
         "minimal"),
    Role("advocate", "User advocate",
         "You represent the end user / the person affected. Focus on usability, clarity, fairness, "
         "safety and what they actually need, not what is convenient to build.",
         "minimal"),
    Role("generalist", "Generalist",
         "You are a thoughtful generalist council member. Give your honest, well-reasoned view.",
         "core"),
]}


def get_role(key: str) -> Role:
    if key not in ROLES:
        raise ValueError(f"unknown council role '{key}'. Known: {', '.join(ROLES)}")
    return ROLES[key]
