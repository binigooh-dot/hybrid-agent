# Hybrid Agent — Claude + a local model

A tool-using AI agent that **runs entirely on your own machine with no API key**
using a local model (Ollama, llama.cpp, LM Studio…). If you add an Anthropic key,
it uses **Claude** as its main model and falls back to the local model when Claude is unreachable.
Claude can also hand simple jobs to the local model for free.

- **No dependencies needed for local mode.** Everything uses Python's standard library.
- **16 built-in tools**: files, shell, Python, web fetch/search, memory, planning, calculator, clock, delegation.
- **Safety:** file tools stay inside a sandboxed workspace, dangerous shell commands are blocked, and risky tools ask y/N first.
- **Tested offline:** 20 tests, no model or network needed.

```
            ┌────────────── you ──────────────┐
            ▼                                 ▲
   ┌─────────────────┐   tool calls   ┌──────────────┐
   │   Agent loop    │ ─────────────► │ Tool registry│──► files / shell / web / memory …
   │   (agent.py)    │ ◄───────────── │              │
   └────────┬────────┘    results     └──────────────┘
            │ chat()
   ┌────────▼────────┐
   │     Router      │── Claude (optional, needs key)
   │                 │── Local model (mandatory, no key)  ◄── fallback
   └─────────────────┘
```

## Quick start (no API key)

```bash
# 1. Install Ollama (https://ollama.com/download), then:
ollama serve &                 # starts the local model server on :11434
ollama pull qwen2.5:7b         # ~4.7 GB; see docs/LOCAL_MODEL_SETUP.md for smaller/larger options

# 2. Check that everything is in place
python3 -m hybrid_agent doctor

# 3. Chat
python3 -m hybrid_agent --backend local
```

To test the agent loop before you download a model, run the canned demo:
```bash
python3 -m hybrid_agent --backend scripted -y -p "demo"
```

## Adding Claude (optional)

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python3 -m hybrid_agent            # backend "auto" now picks Claude, local model as fallback
```

## Commands

| Command | What it does |
|---|---|
| `python3 -m hybrid_agent` | Interactive chat (`/help`, `/tools`, `/reset`, `/usage`, `/exit`) |
| `python3 -m hybrid_agent -p "..."` | One-shot prompt |
| `python3 -m hybrid_agent doctor` | Readiness check (required vs optional) |
| `python3 -m hybrid_agent tools` | List the tools |
| `--backend auto\|claude\|local\|scripted` | Choose the model |
| `--model llama3.1:8b` | Choose the local model |
| `--workspace DIR` | The sandbox folder the agent works in (default `./workspace`) |
| `-y` | Auto-approve risky tools (shell, python, overwrites) |
| `python3 -m unittest discover -s tests -v` | Run the tests |

Settings are read from environment variables or a `.env` file. See [`.env.example`](.env.example).

## Documentation

| File | Contents |
|---|---|
| [NOTES.md](NOTES.md) | Build log: what was done, why, and what was verified |
| [docs/OFFLINE_REQUIREMENTS.md](docs/OFFLINE_REQUIREMENTS.md) | **Everything the agent needs to run without an API key** |
| [docs/LOCAL_MODEL_SETUP.md](docs/LOCAL_MODEL_SETUP.md) | Installing Ollama / llama.cpp / LM Studio; choosing a model |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the pieces fit, with diagrams |
| [docs/TOOLS.md](docs/TOOLS.md) | Reference for each tool, and how to add your own |

## Using it as a library

```python
from pathlib import Path
from hybrid_agent import Agent
from hybrid_agent.backends import LocalBackend
from hybrid_agent.tools import ToolContext, build_default_registry

ctx = ToolContext(workspace=Path("workspace"), approver=lambda *a: True)
tools = build_default_registry(ctx)

@tools.tool("shout", "Upper-case some text", {
    "type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})
def shout(ctx, text):
    return text.upper()

agent = Agent(LocalBackend("qwen2.5:7b"), tools)
print(agent.run("Shout 'hello', then save the result to hello.txt"))
```
