"""[CLI / main] Command-line interface.

    python -m hybrid_agent                          # interactive chat
    python -m hybrid_agent -p "do X"                # one-shot
    python -m hybrid_agent --backend local          # force the local model
    python -m hybrid_agent --tools coding           # choose a tool profile
    python -m hybrid_agent --backend scripted -p x  # smoke test, no model needed
    python -m hybrid_agent doctor                   # check setup
    python -m hybrid_agent tools                    # list tools by category
    python -m hybrid_agent council -p "question" --protocol debate --rounds 2
    python -m hybrid_agent council --council-config examples/council.example.json -p "..."
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
from pathlib import Path

from ..backends import BackendUnavailable, build_backend, build_local_backend
from ..backends.router import RouterBackend
from ..core.agent import Agent
from ..core.config import Config
from ..tools import PROFILES, ToolContext, build_full_registry, build_registry
from . import doctor

DIM, BOLD, CYAN, YELLOW, RED, GREEN, RESET = ("\033[2m", "\033[1m", "\033[36m", "\033[33m",
                                             "\033[31m", "\033[32m", "\033[0m")
_PROMPT_LOCK = threading.Lock()  # council members may ask for approval from several threads


def make_approver(auto: bool):
    def approve(name: str, args: dict, reason: str) -> bool:
        if auto:
            return True
        with _PROMPT_LOCK:
            preview = json.dumps(args)[:300]
            try:
                ans = input(f"{YELLOW}Allow {name} ({reason})? {preview}\n[y/N] {RESET}")
            except EOFError:
                return False
        return ans.strip().lower() in {"y", "yes"}
    return approve


def ask_user(question: str) -> str:
    with _PROMPT_LOCK:
        try:
            return input(f"{YELLOW}Agent asks: {question}\n> {RESET}") or "(no answer)"
        except EOFError:
            return "(No user is available to answer. Make a reasonable assumption and state it.)"


def print_event(kind: str, data: dict) -> None:
    who = f"{data['agent']}: " if data.get("agent", "agent") != "agent" else ""
    if kind == "tool_call":
        print(f"{CYAN}  -> {who}{data['name']}({json.dumps(data['arguments'])[:200]}){RESET}")
    elif kind == "tool_result":
        colour = RED if data["is_error"] else DIM
        first = data["preview"].splitlines()[0][:150] if data["preview"] else ""
        print(f"{colour}     {first}{RESET}")
    elif kind == "thought":
        print(f"{DIM}  {data['text'][:300]}{RESET}")
    elif kind == "council":
        ev = data["event"]
        if ev == "round_start":
            print(f"{BOLD}== round {data['round']}: {data['kind']} ({', '.join(data['members'])}){RESET}")
        elif ev == "member_done":
            status = f"{RED}failed: {data['error']}" if data["error"] else f"{GREEN}done"
            print(f"  {data['member']} [{data['kind']}] {status}{RESET} {DIM}{data['seconds']:.1f}s{RESET}")
        elif ev in {"consensus", "options", "no_options", "chair_failed"}:
            print(f"{YELLOW}  ({ev}: {data.get('winner') or data.get('options') or data.get('detail')}){RESET}")


def resolve_profile(cfg: Config, using_claude: bool) -> str:
    if cfg.tool_profile == "auto":
        return "full" if using_claude else "core"
    return cfg.tool_profile


def build_agent(cfg: Config, verbose: bool = True) -> Agent:
    backend = build_backend(cfg)
    using_claude = isinstance(backend, RouterBackend)
    ctx = ToolContext(
        workspace=cfg.workspace,
        approver=make_approver(cfg.auto_approve),
        ask_user=ask_user,
        max_output=cfg.max_tool_output,
        shell_timeout=cfg.shell_timeout,
        searxng_url=cfg.searxng_url,
        local_backend=build_local_backend(cfg) if using_claude else None,
    )
    cfg.workspace.mkdir(parents=True, exist_ok=True)
    tools = build_registry(ctx, resolve_profile(cfg, using_claude), include_delegate=using_claude)
    return Agent(backend, tools, max_steps=cfg.max_steps, log_dir=cfg.log_dir,
                 on_event=print_event if verbose else None)


def list_tools(cfg: Config) -> None:
    reg = build_full_registry(ToolContext(workspace=cfg.workspace))
    marks = {"read": "", "network": " [net]", "write": " [write]", "execute": " [exec]"}
    print(f"{BOLD}{len(reg)} tools{RESET}   risk labels: [net] network, [write] changes files, "
          f"[exec] runs code;  * = asks approval\n")
    for cat, names in reg.categories().items():
        print(f"{BOLD}{cat}{RESET}")
        for n in names:
            t = reg.get(n)
            star = "*" if t.requires_approval else ""
            print(f"  {n}{star}{DIM}{marks[t.risk]}{RESET}  {t.description.split('. ')[0][:90]}")
        print()
    print(f"{BOLD}Profiles{RESET} (--tools / AGENT_TOOL_PROFILE): {', '.join(PROFILES)}")


def repl(agent: Agent) -> None:
    print(f"{BOLD}Hybrid agent{RESET} - brain: {agent.backend.describe()} - {len(agent.tools)} tools")
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
            for cat, names in agent.tools.categories().items():
                print(f"{cat}: {', '.join(names)}")
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


def run_council(cfg: Config, args) -> int:
    from ..council import Council, CouncilError
    question = args.prompt
    if not question:
        try:
            question = input(f"{BOLD}Question for the council> {RESET}").strip()
        except EOFError:
            question = ""
    if not question:
        print(f"{RED}Give a question with -p{RESET}", file=sys.stderr)
        return 2
    council = Council.from_config(cfg.council_config, cfg,
                                  on_event=None if args.quiet else print_event,
                                  approver=make_approver(cfg.auto_approve), ask_user=ask_user)
    print(f"{BOLD}Council{RESET}\n{council.describe()}\n")
    options = [o.strip() for o in args.options.split(",")] if args.options else None
    try:
        result = council.deliberate(question, protocol=args.protocol, rounds=args.rounds, options=options)
    except CouncilError as e:
        print(f"{RED}{e}{RESET}", file=sys.stderr)
        return 2
    path = result.save(cfg.log_dir)
    print(f"\n{BOLD}=== Council answer ({result.protocol}) ==={RESET}")
    if result.tally:
        print(f"{YELLOW}Vote: {result.tally['summary']}{RESET}\n")
    print(result.final_answer)
    print(f"\n{DIM}Transcript: {path}  ·  tokens {result.usage}  ·  {result.seconds:.1f}s{RESET}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hybrid_agent", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["chat", "doctor", "tools", "council"], default="chat")
    ap.add_argument("-p", "--prompt", help="run a single prompt (or council question) and exit")
    ap.add_argument("--backend", choices=["auto", "claude", "local", "scripted"])
    ap.add_argument("--model", help="local model name (e.g. qwen2.5:7b)")
    ap.add_argument("--tools", help="tool profile, e.g. core | coding | research | full | 'core,+weather'")
    ap.add_argument("--workspace", type=Path)
    ap.add_argument("-y", "--yes", action="store_true", help="auto-approve risky tools")
    ap.add_argument("-q", "--quiet", action="store_true", help="hide tool activity")
    ap.add_argument("--debug", action="store_true")
    council = ap.add_argument_group("council")
    council.add_argument("--protocol", choices=["roundtable", "debate", "vote", "critique"])
    council.add_argument("--rounds", type=int)
    council.add_argument("--options", help="comma-separated options to vote on")
    council.add_argument("--council-config", type=Path, help="JSON file describing the members")
    council.add_argument("--workers", type=int, help="members answering in parallel")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()
    for attr, val in (("backend", args.backend), ("local_model", args.model), ("tool_profile", args.tools),
                      ("workspace", args.workspace), ("council_config", args.council_config),
                      ("council_workers", args.workers)):
        if val is not None:
            setattr(cfg, attr, val)
    if args.yes:
        cfg.auto_approve = True

    if args.command == "doctor":
        return doctor.main(cfg)
    if args.command == "tools":
        list_tools(cfg)
        return 0
    cfg.workspace.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "council":
            return run_council(cfg, args)
        agent = build_agent(cfg, verbose=not args.quiet)
    except (BackendUnavailable, ValueError) as e:
        print(f"{RED}{e}{RESET}", file=sys.stderr)
        return 2

    if args.prompt:
        try:
            print(agent.run(args.prompt))
        except BackendUnavailable as e:
            print(f"{RED}Model unavailable: {e}{RESET}", file=sys.stderr)
            return 2
        return 0
    repl(agent)
    return 0
