"""[AGENTS / build] Turn one of your agents into a working Agent: its model, tools and safety settings.

Used by Chat and by scheduled tasks, so both behave the same way.
"""
from __future__ import annotations

import platform

from ..backends import build_backend, build_backend_from_spec, build_local_backend
from ..backends.router import RouterBackend
from ..core.agent import DEFAULT_SYSTEM_PROMPT, Agent
from ..core.config import Config
from ..tools import ToolContext, build_registry
from .store import load_agents


def build_agent(cfg: Config, agent_id: str | None = None, *, profile: str | None = None, approver=None,
                asker=None, on_event=None, extra_prompt: str = "", name: str = "chat") -> Agent:
    agent = load_agents(cfg.agents_dir).get(agent_id) if agent_id else None
    if agent_id and agent is None:
        raise ValueError(f"unknown agent '{agent_id}'")
    model = agent.model if agent else "default"
    backend = build_backend(cfg) if model == "default" else build_backend_from_spec(model, cfg, member=agent_id or name)
    claude = isinstance(backend, RouterBackend)
    ctx = ToolContext.from_config(cfg, approver=approver, ask_user=asker,
                                  local_backend=build_local_backend(cfg) if claude else None)
    tools = build_registry(ctx, profile or ("full" if claude else "core"), include_delegate=claude,
                           safe_mode=cfg.safe_mode)
    system = DEFAULT_SYSTEM_PROMPT.format(os=platform.system())
    if agent:
        system += f"\n\nYour name is {agent.name}."
    if extra_prompt:
        system += f"\n\n{extra_prompt}"
    return Agent(backend, tools, system_prompt=system, max_steps=cfg.max_steps, log_dir=cfg.log_dir,
                 name=agent.id if agent else name, on_event=on_event, context_chars=cfg.context_chars())
