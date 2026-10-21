# Hybrid Agent: Claude + local models, 78 tools, council of agents

A tool-using AI agent that **runs entirely on your own machine with no API key** using a local
model (Ollama, llama.cpp, LM Studio…). If you add an Anthropic key, it uses **Claude** as its main
model and falls back to the local model when Claude is unreachable. Several agents can also sit
as a **council** and deliberate together.

- **78 built-in tools in 16 categories**: files, shell, code/git, data (CSV/JSON/SQLite/XML), text,
  maths, time, web, network, knowledge (Wikipedia, arXiv, weather, dictionary, RSS), system,
  archives, memory, local document search, planning, and a council blackboard. **None needs an API key.**
- **Tool profiles** give each agent only the tools it needs (7–23), so small local models aren't overwhelmed.
- **Council of agents** with roles, mixed models, a shared blackboard, and four protocols (roundtable, debate, vote, critique).
- **No dependencies** in local mode, which uses only Python's standard library. `anthropic` is needed only for Claude.
- **Safety:** a workspace sandbox, a blocklist for destructive commands, approval prompts, and risk labels on every tool.
- **87 offline tests** need no model, key or internet.

```
                 ┌───────────────── you ─────────────────┐
                 ▼                                       ▼
        ┌─────────────────┐                     ┌──────────────────┐
        │   Agent loop    │◄── one per member ──│     Council      │── blackboard
        └───┬─────────┬───┘                     │ roles · protocols│
   chat()   │         │ tool calls              └──────────────────┘
   ┌────────▼───┐ ┌───▼──────────────────────────────────────────┐
   │  Router    │ │ Tool registry ─ profile ─► 78 tools / 16 cats │
   │ Claude ────┼─┤ validate → approve → safety → run → truncate  │
   │ ↓ fallback │ └───────────────────────────────────────────────┘
   │ Local model│  ← the required piece: needs no key
   └────────────┘
```

## Quick start (no API key)

```bash
# 1. Install Ollama (https://ollama.com/download), then:
ollama serve &
ollama pull qwen2.5:7b                 # ~4.7 GB; see docs/02 for other sizes

# 2. Check the setup
python3 -m hybrid_agent doctor

# 3. Chat with one agent
python3 -m hybrid_agent --backend local

# 4. Ask a council
python3 -m hybrid_agent council -p "Should I learn Rust or Go first?" --protocol debate
```

Try it before downloading any model:
```bash
python3 -m hybrid_agent --backend scripted -y -p demo
python3 -m hybrid_agent council --backend scripted -p "test question" --protocol vote
```

## Adding Claude (optional)

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python3 -m hybrid_agent             # "auto" picks Claude, with the local model as fallback
```

With Claude as the main model, the agent gets the `full` tool profile plus `delegate_to_local`,
which hands simple jobs to the free local model.

## Commands

| Command | What it does |
|---|---|
| `python3 -m hybrid_agent` | Interactive chat (`/help`, `/tools`, `/reset`, `/usage`, `/exit`) |
| `python3 -m hybrid_agent -p "..."` | One-shot prompt |
| `python3 -m hybrid_agent council -p "..."` | Council deliberation (`--protocol`, `--rounds`, `--options`, `--council-config`, `--workers`) |
| `python3 -m hybrid_agent tools` | All tools, grouped by category, with risk labels |
| `python3 -m hybrid_agent doctor` | Readiness check (required vs optional) |
| `--backend auto\|claude\|local\|scripted` | Choose the model (`scripted` = offline demo / council dry run) |
| `--tools PROFILE` | `minimal`, `core`, `research`, `coding`, `data`, `readonly`, `readonly_all`, `full`, or e.g. `core,+weather` |
| `--model llama3.1:8b` | Choose the local model |
| `--workspace DIR` | The sandbox folder the agent works in (default `./workspace`) |
| `-y` | Auto-approve risky tools |
| `python3 -m unittest discover -s tests -t .` | Run the tests |

Settings come from environment variables or `.env`; see [`.env.example`](.env.example).

## Project layout

```
hybrid-agent/
├── hybrid_agent/
│   ├── core/        [CORE]      agent loop, messages, config, safety, errors
│   ├── backends/    [BACKENDS]  local (Ollama/OpenAI-compatible), claude, router, scripted
│   ├── tools/       [TOOLS]     registry, profiles
│   │   └── builtin/             15 tool modules (files, shell, code, data, text, math_time,
│   │                            web, network, knowledge, system, archives, memory,
│   │                            documents, agent_ops, council_board)
│   ├── council/     [COUNCIL]   blackboard, roles, member, ballots, protocols, council
│   └── cli/         [CLI]       main, doctor
├── tests/           [TESTS]     one file per area (87 tests, all offline)
├── examples/        [EXAMPLE]   council configs, custom tool, council from Python
├── scripts/         [SCRIPTS]   regenerate the tool reference and the file map
├── docs/            [DOCS]      numbered guides (see below)
└── NOTES.md                     build log: what was done, why, and what was verified
```

Every Python file starts with a `[LAYER / name]` label. [docs/FILE_MAP.md](docs/FILE_MAP.md) lists them all.

## Documentation

| Doc | Contents |
|---|---|
| [NOTES.md](NOTES.md) | Build log, review findings, decisions, verification |
| [docs/01_OFFLINE_REQUIREMENTS.md](docs/01_OFFLINE_REQUIREMENTS.md) | **Everything needed to run without an API key** |
| [docs/02_LOCAL_MODEL_SETUP.md](docs/02_LOCAL_MODEL_SETUP.md) | Ollama / llama.cpp / LM Studio; choosing models |
| [docs/03_ARCHITECTURE.md](docs/03_ARCHITECTURE.md) | Layers, diagrams, design decisions |
| [docs/04_TOOLS.md](docs/04_TOOLS.md) | Full tool catalogue, profiles, safety, adding tools (generated) |
| [docs/05_COUNCIL.md](docs/05_COUNCIL.md) | Council of agents: roles, protocols, configs, next steps |
| [docs/FILE_MAP.md](docs/FILE_MAP.md) | Every file and its label (generated) |
