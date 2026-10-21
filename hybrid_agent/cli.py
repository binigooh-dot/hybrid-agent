"""Command-line interface.

    python -m hybrid_agent                    # interactive chat
    python -m hybrid_agent -p "do X"          # one-shot
    python -m hybrid_agent --backend local    # force local model
    python -m hybrid_agent --backend scripted # smoke test, no model needed
    python -m hybrid_agent doctor             # check setup
    python -m hybrid_agent tools              # list tools
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import doctor
from .agent import Agent
from .backends import BackendUnavailable, build_backend, build_local_backend
from .backends.router import RouterBackend
from .config import Config
from .tools import ToolContext, build_default_registry

DIM, BOLD, CYAN, YELLOW, RED, RESET = "\033[2m", "\033[1m", "\033[36m", "\033[33m", "\033[31m", "\033[0m"


def make_approver(auto: bool):
    def approve(name: str, args: dict, reason: str) -> bool:
        if auto:
            return True
        preview = json.dumps(args)[:300]
        try:
            ans = input(f"{YELLOW}Allow {name} ({reason})? {preview}\n[y/N] {RESET}")
        except EOFError:
            return False
        return ans.strip().lower() in {"y", "yes"}
    return approve


def print_event(kind: str, data: dict) -> None:
    if kind == "tool_call":
        print(f"{CYAN}  -> {data['name']}({json.dumps(data['arguments'])[:200]}){RESET}")
    elif kind == "tool_result":
        colour = RED if data["is_error"] else DIM
        first = data["preview"].splitlines()[0][:150] if data["preview"] else ""
        print(f"{colour}     {first}{RESET}")
    elif kind == "thought":
        print(f"{DIM}  {data['text'][:300]}{RESET}")


def build_agent(cfg: Config, verbose: bool = True) -> Agent:
    backend = build_backend(cfg)
    using_claude = isinstance(backend, RouterBackend)
    ctx = ToolContext(
        workspace=cfg.workspace,
        approver=make_approver(cfg.auto_approve),
        max_output=cfg.max_tool_output,
        shell_timeout=cfg.shell_timeout,
        searxng_url=cfg.searxng_url,
        local_backend=build_local_backend(cfg) if using_claude else None,
    )
    cfg.workspace.mkdir(parents=True, exist_ok=True)
    tools = build_default_registry(ctx, include_delegate=using_claude)
    return Agent(backend, tools, max_steps=cfg.max_steps, log_dir=cfg.log_dir,
                 on_event=print_event if verbose else None)


def repl(agent: Agent) -> None:
    print(f"{BOLD}Hybrid agent{RESET} - brain: {agent.backend.describe()}")
    print(f"{DIM}Workspace: {agent.tools.ctx.workspace.resolve()}   /help for commands{RESET}\n")
    while True:
        try:
            line = input(f"{BOLD}you> {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in {"/exit", "/quit"}:
            return
        if line == "/help":
            print("/reset  clear conversation   /tools  list tools   /usage  token totals   /exit")
            continue
        if line == "/reset":
            agent.reset()
            print("(conversation cleared)")
            continue
        if line == "/tools":
            print(", ".join(agent.tools.names()))
            continue
        if line == "/usage":
            print(agent.usage)
            continue
        try:
            answer = agent.run(line)
        except BackendUnavailable as e:
            print(f"{RED}Model unavailable: {e}{RESET}")
            continue
        except KeyboardInterrupt:
            print(f"\n{YELLOW}(interrupted){RESET}")
            continue
        print(f"\n{BOLD}agent>{RESET} {answer}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hybrid_agent", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["chat", "doctor", "tools"], default="chat")
    ap.add_argument("-p", "--prompt", help="run a single prompt and exit")
    ap.add_argument("--backend", choices=["auto", "claude", "local", "scripted"])
    ap.add_argument("--model", help="local model name (e.g. qwen2.5:7b)")
    ap.add_argument("--workspace", type=Path)
    ap.add_argument("-y", "--yes", action="store_true", help="auto-approve risky tools")
    ap.add_argument("-q", "--quiet", action="store_true", help="hide tool activity")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()
    if args.backend:
        cfg.backend = args.backend
    if args.model:
        cfg.local_model = args.model
    if args.workspace:
        cfg.workspace = args.workspace
    if args.yes:
        cfg.auto_approve = True

    if args.command == "doctor":
        return doctor.main(cfg)

    try:
        agent = build_agent(cfg, verbose=not args.quiet)
    except BackendUnavailable as e:
        print(f"{RED}{e}{RESET}", file=sys.stderr)
        return 2

    if args.command == "tools":
        for spec in agent.tools.specs():
            print(f"{BOLD}{spec['name']}{RESET}: {spec['description']}")
        return 0
    if args.prompt:
        try:
            print(agent.run(args.prompt))
        except BackendUnavailable as e:
            print(f"{RED}Model unavailable: {e}{RESET}", file=sys.stderr)
            return 2
        return 0
    repl(agent)
    return 0
