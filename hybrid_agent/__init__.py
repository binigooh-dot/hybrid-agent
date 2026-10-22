"""[PACKAGE] hybrid_agent - AI helpers that run on a local model (no API key), with
Claude as an optional brain. Agents chat, decide together as a council, and run
scheduled tasks, behind several safety layers.

Package map (every module's docstring starts with its [LAYER / name] label):

    core/        [CORE]        agent loop, messages, config, errors
    security/    [SECURITY]    workspace fence, sandbox, protected paths, backups, audit, network guard
    backends/    [BACKENDS]    model connectors: local, claude, router, scripted
    tools/       [TOOLS]       registry framework, profiles, builtin/ tool modules
    council/     [COUNCIL]     multi-agent deliberation
    agents/      [AGENTS]      your agents: a name, an ASCII smiley face and a model
    tasks/       [TASKS]       task queue and scheduler
    runtime/     [RUNTIME]     the local model engine, kept in the home folder
    gui/         [GUI]         the app (local web interface)
    diagnostics/ [DIAGNOSTICS] safety fire drills, integrity checks
    cli/         [CLI]         command line, doctor
"""
from .core.agent import Agent
from .core.config import Config

__all__ = ["Agent", "Config"]
__version__ = "1.2.0"
