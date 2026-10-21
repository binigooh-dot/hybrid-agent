"""[PACKAGE] hybrid_agent - a tool-using agent that runs on a local model (no API key)
and can optionally use Claude as its primary brain. Includes a council
framework for several agents to deliberate together.

Package map (every module's docstring starts with its [LAYER / name] label):

    core/       [CORE]      agent loop, messages, config, safety, errors
    backends/   [BACKENDS]  model connectors: local, claude, router, scripted
    tools/      [TOOLS]     registry framework, profiles, builtin/ tool modules
    council/    [COUNCIL]   multi-agent deliberation groundwork
    cli/        [CLI]       command line, doctor
"""
from .core.agent import Agent
from .core.config import Config

__all__ = ["Agent", "Config"]
__version__ = "0.2.0"
