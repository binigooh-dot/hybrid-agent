"""[COUNCIL / member] Council member definition (MemberSpec) and runtime wrapper (CouncilMember).

A MemberSpec is plain data - easy to write in a JSON config:

    {"name": "skeptic", "role": "skeptic", "backend": "local:llama3.1:8b",
     "tools": "readonly,+web_search", "weight": 1.0}

backend strings:
    "default"            whatever the main agent uses (AGENT_BACKEND)
    "local"              the configured local model
    "local:<model>"      a specific local model, e.g. "local:qwen2.5:14b"
    "claude"             Claude (configured model), local fallback
    "claude:<model>"     a specific Claude model, e.g. "claude:claude-sonnet-5-5"
    "scripted"           canned demo replies (tests / offline demo)
or a Backend instance (programmatic use / tests).
"""
from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Any

from ..core.agent import Agent
from .roles import get_role

MEMBER_SYSTEM_PROMPT = """\
{persona}

You are "{name}", the {title} on a council of AI agents that deliberates on
questions together. Other members: {others}.

How the council works:
- You will receive the question, then later the other members' positions.
- Think independently. Agree when persuaded by evidence, not by numbers.
- You can use your tools (workspace on {os}) to check facts before answering.
- board_post shares findings with the council; board_read shows what others shared.
- Keep each contribution focused: lead with your position, then your reasons.
"""


@dataclass
class MemberSpec:
    name: str
    role: str = "generalist"
    backend: Any = "default"        # str spec or Backend instance (see module docstring)
    tools: str | None = None        # profile string; default = the role's profile
    persona: str | None = None      # overrides the role's persona text
    weight: float = 1.0             # vote weight
    max_steps: int | None = None    # tool-use steps per contribution

    @classmethod
    def from_dict(cls, d: dict) -> "MemberSpec":
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown member field(s): {', '.join(sorted(unknown))}")
        if "name" not in d:
            raise ValueError("every council member needs a 'name'")
        get_role(d.get("role", "generalist"))  # validate early
        return cls(**d)

    def system_prompt(self, others: list[str]) -> str:
        role = get_role(self.role)
        return MEMBER_SYSTEM_PROMPT.format(
            persona=self.persona or role.persona, name=self.name, title=role.title,
            others=", ".join(others) or "none", os=platform.system())

    def tool_profile(self) -> str:
        return self.tools or get_role(self.role).tools


@dataclass
class CouncilMember:
    """A spec plus its live Agent (own model, own tools, own memory of the session)."""
    spec: MemberSpec
    agent: Agent

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def role(self) -> str:
        return self.spec.role

    def ask(self, prompt: str) -> str:
        return self.agent.run(prompt)
