# Hybrid Agent: local agents, a council with faces, and Claude when you want it

A tool-using AI agent that **runs entirely on your own computer with no API key** (a local model does
the thinking), an optional **Claude** brain, a **council** of persona agents with animated **ASCII
faces** that deliberate together, and **Agent Studio**, a local web GUI to drive it all.

- **80 tools in 16 categories** (files, shell, code/git, data, text, maths, time, web, network,
  knowledge, system, archives, memory, document search, planning, council board). **None needs a key.**
- **Tool profiles** give each agent only what it needs (7–23 tools), so small models stay sharp.
- **Council** with 8 roles, 4 protocols (roundtable, debate, vote, critique), mixed models and a shared blackboard.
- **Personas with ASCII faces:** Sage, Vex and Nova built in, 7 expressions, talking and thinking animations, ~2 KB each, and a face builder in the GUI.
- **Agent Studio GUI:** a 3-step council with a live stage, chat, face builder, tool browser, a safety centre with one-click undo, and clear Allow/Deny approvals.
- **Agent Builder Knowledge Suite:** an interactive guide in one HTML file → [docs/agent_builder_suite.html](docs/agent_builder_suite.html)
- **Hard safety:** commands run in a kernel sandbox (system read-only, home hidden, CPU/memory/file caps), protected system/hardware/agent files, automatic backups with undo, a disk guard, safe mode, an audit log and an integrity manifest. **39 safety fire drills, all passing** (see [docs/07](docs/07_SAFETY_AND_DIAGNOSTICS.md)).
- **Clean bill of health:** ruff, mypy, bandit, vulture all clean; Python 3.10+; tests pass on 3.11–3.13.
- **No dependencies** in local mode (standard library only).

```
                 ┌──────────────── you ────────────────┐
                 ▼                                     ▼
        ┌─────────────────┐   one per member   ┌──────────────────┐
        │   Agent loop    │◄───────────────────│ Council + faces  │── blackboard
        └───┬─────────┬───┘                    └──────────────────┘
   chat()   │         │ tool calls                     ▲
   ┌────────▼───┐ ┌───▼──────────────────────┐  ┌──────┴───────┐
   │  Router    │ │ 80 tools via a profile   │  │ Agent Studio │ 127.0.0.1 only
   │ Claude ────┤ │ validate → approve →     │  │ (web GUI)    │
   │ ↓ fallback │ │ security → run → limit   │  └──────────────┘
   │ Local model│ └──────────────────────────┘
   └────────────┘   ← needs no key
```

## Quick start (no API key)

```bash
# 1. Install Ollama (https://ollama.com/download), then:
ollama serve &
ollama pull qwen2.5:7b                 # ~4.7 GB; see docs/02 for other sizes

# 2. Check setup and safety
python3 -m hybrid_agent doctor
python3 -m hybrid_agent diagnose

# 3. Use it
python3 -m hybrid_agent gui            # the GUI (opens your browser)
python3 -m hybrid_agent --backend local                    # terminal chat
python3 -m hybrid_agent council --personas sage,vex,nova -p "Rust or Go first?" --protocol vote --options "Rust,Go"
```

Try everything before downloading a model:
```bash
python3 -m hybrid_agent gui --backend scripted
python3 -m hybrid_agent council --backend scripted --personas sage,vex,nova -p "test"
```

**Add Claude (optional):** `pip install anthropic`, then `export ANTHROPIC_API_KEY=sk-ant-...`. In `auto`
mode the agent then uses Claude, with the local model as fallback.

## Commands

| Command | What it does |
|---|---|
| `python3 -m hybrid_agent` | Terminal chat (`/help`, `/tools`, `/reset`, `/usage`, `/exit`) |
| `python3 -m hybrid_agent -p "..."` | One-shot prompt |
| `python3 -m hybrid_agent gui` | Agent Studio web GUI (`--port`, `--no-browser`) |
| `python3 -m hybrid_agent council -p "..."` | Council (`--personas`, `--protocol`, `--rounds`, `--options`, `--council-config`, `--workers`) |
| `python3 -m hybrid_agent diagnose` | Safety fire drills + integrity checks (`--only`, `--json`) |
| `python3 -m hybrid_agent doctor` | Setup check (required vs optional) |
| `python3 -m hybrid_agent tools` | All tools by category, with risk labels |
| `--backend auto\|claude\|local\|scripted` · `--model` · `--tools PROFILE` · `--workspace DIR` · `-y` | Common options |
| `AGENT_SANDBOX=strict` · `AGENT_SAFE_MODE=1` · `AGENT_MIN_FREE_MB` | Safety settings (see docs/07) |
| `python3 scripts/health_check.py` | Full code-health scorecard (tests, lint, types, security, drills, browser) |

Settings come from environment variables or `.env`; see [`.env.example`](.env.example).

## Project layout

```
hybrid-agent/
├── hybrid_agent/
│   ├── core/         [CORE]         agent loop, messages, config, errors
│   ├── security/     [SECURITY]     fence, blocklist, sandbox, protected paths, backups, audit, network guard
│   ├── backends/     [BACKENDS]     local (Ollama / OpenAI-compatible), claude, router, scripted
│   ├── tools/        [TOOLS]        registry, profiles, builtin/ (15 modules, 80 tools)
│   ├── council/      [COUNCIL]      roles, members, protocols, ballots, blackboard
│   ├── personas/     [PERSONAS]     characters + animated ASCII faces; presets/ (Sage, Vex, Nova)
│   ├── gui/          [GUI]          local web server, live events, approvals, knowledge-suite builder, static/
│   ├── diagnostics/  [DIAGNOSTICS]  safety fire drills, tripwire harness, integrity checks
│   └── cli/          [CLI]          command line, doctor
├── personas/         your persona files (the GUI saves here)
├── tests/            [TESTS]        one file per area: all offline
├── examples/         [EXAMPLE]      council configs (role-based, personas, local-only), library usage
├── scripts/          [SCRIPTS]      health check, browser smoke test, doc generators
├── docs/             [DOCS]         numbered guides 01–07 + the interactive knowledge suite
└── NOTES.md                         build log: what was done, why, and what was verified
```
Every source file starts with a `[LAYER / name]` label. [docs/FILE_MAP.md](docs/FILE_MAP.md) lists them all.

## Documentation

| Doc | Contents |
|---|---|
| [docs/agent_builder_suite.html](docs/agent_builder_suite.html) | **Interactive guide**: tool explorer, profile builder, council designer, faces, safety, glossary |
| [NOTES.md](NOTES.md) | Build log, review findings, decisions, verification |
| [01 Offline requirements](docs/01_OFFLINE_REQUIREMENTS.md) | Everything needed to run without an API key |
| [02 Local model setup](docs/02_LOCAL_MODEL_SETUP.md) | Ollama / llama.cpp / LM Studio; choosing models |
| [03 Architecture](docs/03_ARCHITECTURE.md) | Layers, diagrams, design decisions |
| [04 Tools](docs/04_TOOLS.md) | Full tool catalogue, profiles, adding tools (generated) |
| [05 Council](docs/05_COUNCIL.md) | Roles, protocols, configs, personas in councils |
| [06 GUI & personas](docs/06_GUI_AND_PERSONAS.md) | Agent Studio, ASCII faces and animations, roadmap |
| [07 Safety & diagnostics](docs/07_SAFETY_AND_DIAGNOSTICS.md) | Protective layers, fire-drill results, code health |
