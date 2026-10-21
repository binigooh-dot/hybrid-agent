# 01 · What the agent needs to run without an API key

Running the agent without a key means **the local model does all the thinking**.
Think of the agent as a car:

| Car part | Agent part | Needs a key? |
|---|---|---|
| Engine | The **local model** (e.g. qwen2.5 running in Ollama) | No |
| Fuel line | The **local backend**, which sends the conversation to the model over HTTP | No |
| Steering + driver | The **agent loop** (think → use a tool → look at the result → repeat) | No |
| Hands | The **tools** (files, shell, web…) | No |
| Seatbelt + brakes | **Safety**: sandbox, command blocklist, approval prompts | No |
| Dashboard | **Doctor** (readiness check) and **logs** | No |
| Turbocharger | **Claude** | Yes. Optional |

Everything except the turbocharger is required, and everything except the turbocharger is
included in this repo.

---

## Checklist

### A. On your machine (install yourself)

| # | Requirement | Why it's mandatory | How |
|---|---|---|---|
| 1 | **Python 3.10+** | Runs the agent | python.org or your OS package manager |
| 2 | **A local model server** | Replaces the Claude API | [Ollama](https://ollama.com/download) (recommended), or llama.cpp `llama-server`, LM Studio, vLLM. See [02_LOCAL_MODEL_SETUP.md](02_LOCAL_MODEL_SETUP.md) |
| 3 | **A downloaded model** | The server needs weights to load | `ollama pull qwen2.5:7b` |
| 4 | **Enough RAM/VRAM** | Models must fit in memory | ~8 GB RAM for a 7B model at 4-bit; see the sizing table in LOCAL_MODEL_SETUP.md |
| 5 | **A writable workspace folder** | Holds files, memory and the plan | Created automatically (`./workspace`) |

Not needed: pip packages, internet access (except for the web tools), or any account.

### B. In this repo (already built)

| # | Component | File | Why it's mandatory without a key |
|---|---|---|---|
| 1 | Provider-neutral message format | `core/messages.py` | Lets the same loop and tools work with any model |
| 2 | **Local backend** (Ollama + OpenAI-compatible) | `backends/local.py` | Without it, the only model is a paid API |
| 3 | **Prompt-mode tool calling** | `backends/local.py` (`parse_prompted_tool_calls`) | Many small or older models have no native tool calling. This reads tool calls from a JSON block in plain text instead, so any instruction-following model works |
| 4 | Auto-detect tool support | `LocalBackend.chat` (`tool_mode="auto"`) | Switches to prompt mode automatically when the server reports "does not support tools" |
| 5 | **Agent loop** with rollback and truncation guard | `core/agent.py` | The think → act → observe cycle. Never runs cut-off tool calls, and cleans up the history if the model fails |
| 6 | **Tool registry + argument validation** | `tools/registry.py` | Local models make more argument mistakes. Clear errors ("unknown argument 'pth' (valid: path…)") let them fix the call |
| 7 | **Tool profiles** | `tools/profiles.py` | All 78 tool descriptions take about 6k tokens, which would fill an 8k local context. Profiles send 7–23 tools instead |
| 8 | **Tool suite** (78 tools, stdlib only) | `tools/builtin/*.py` | What the agent can do. See [04_TOOLS.md](04_TOOLS.md) |
| 9 | **Key-free web search + knowledge** | `tools/builtin/web.py`, `knowledge.py` | DuckDuckGo/SearXNG, Wikipedia, arXiv, Open-Meteo weather and a dictionary: all keyless |
| 10 | **Local document search** (BM25) | `tools/builtin/documents.py` | Searches your files without an embeddings API or model, and keeps context small |
| 11 | **Long-term memory** | `tools/builtin/memory.py` | The local context window is small, so durable facts go into a JSON file |
| 12 | **Safety layer** | `core/safety.py`, approval prompts, risk labels | No vendor-side safety filter sits in front of a local model |
| 13 | **Output truncation** | `ToolRegistry.execute` | One large tool result could fill a small local context window |
| 14 | **Config with key-free defaults** | `core/config.py`, `.env.example` | Default settings never require a key |
| 15 | **Doctor** | `cli/doctor.py` | Separates "required" from "optional" failures, so you can tell why the agent won't start |
| 16 | **Transcript logs** | `core/agent.py` → `logs/*.jsonl` | Smaller models fail more often, and the logs show where |
| 17 | **Scripted/canned backends + offline tests** | `backends/scripted.py`, `tests/` | Test everything, including councils, without a model or the network |
| 18 | **Council framework** | `council/` | Several local models can deliberate with no key at all. See [05_COUNCIL.md](05_COUNCIL.md) |

---|---|---|---|
| 1 | Provider-neutral message format | `hybrid_agent/messages.py` | Lets the same loop and tools work with any model |
| 2 | **Local backend** (Ollama + OpenAI-compatible) | `backends/local.py` | Without it, the only model is a paid API |
| 3 | **Prompt-mode tool calling** | `backends/local.py` (`parse_prompted_tool_calls`) | Many small or older models have no native tool calling. This reads tool calls from a JSON block in plain text instead, so any instruction-following model works |
| 4 | Auto-detect tool support | `LocalBackend.chat` (`tool_mode="auto"`) | Switches to prompt mode automatically when the server reports "does not support tools" |
| 5 | **Agent loop** | `agent.py` | The think → act → observe cycle, with a step limit |
| 6 | **Tool registry + argument validation** | `tools/registry.py` | Local models make more argument mistakes than Claude. Clear validation errors let them fix the call on the next step instead of crashing |
| 7 | **Tool suite** (16 tools) | `tools/*.py` | What the agent can do. See [TOOLS.md](TOOLS.md) |
| 8 | **Key-free web search** | `tools/web.py` | Most search APIs need a key. This uses DuckDuckGo's HTML page, or your own SearXNG server |
| 9 | **Long-term memory** | `tools/memory.py` | The local context window is small (8k tokens by default), so durable facts go into a JSON file |
| 10 | **Safety layer** | `safety.py`, approval prompts | No vendor-side safety filter sits in front of a local model |
| 11 | **Output truncation** | `ToolRegistry.execute` | One large tool result could fill a small local context window |
| 12 | **Config with key-free defaults** | `config.py`, `.env.example` | Default settings never require a key |
| 13 | **Doctor** | `doctor.py` | Separates "required" from "optional" failures, so you can tell why the agent won't start |
| 14 | **Transcript logs** | `agent.py` → `logs/*.jsonl` | Smaller models fail more often, and the logs show where |
| 15 | **Scripted backend + offline tests** | `backends/scripted.py`, `tests/` | Test everything without a model or the network |

---

## Limits of running without a key

- **Smaller models are less reliable.** A 7B model handles simple multi-step tasks well
  and long, complex plans less well. A 14B–32B model is much better if your hardware can run it.
- **Speed depends on your hardware.** With CPU only, expect a few tokens per second.
- **Web search via DuckDuckGo is best-effort.** It can rate-limit you. Run your own
  [SearXNG](https://docs.searxng.org/) and set `SEARXNG_URL` for reliable search.
- **Context is small.** `LOCAL_NUM_CTX=8192` by default. Raise it if you have the memory.
