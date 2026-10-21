# 01 · What the agent needs to run without an API key

Running the agent without a key means **the local model does all the thinking**.
Think of the agent as a car:

| Car part | Agent part | Needs a key? |
|---|---|---|
| Engine | The **local model** (e.g. qwen2.5 running in Ollama) | No |
| Fuel line | The **local backend**, which sends the conversation to the model over HTTP | No |
| Steering + driver | The **agent loop** (think → use a tool → look at the result → repeat) | No |
| Hands | The **tools** (files, shell, web… 80 in all) | No |
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
| 4 | **Enough RAM/VRAM** | Models must fit in memory | ~8 GB RAM for a 7B model at 4-bit; see the sizing table in 02_LOCAL_MODEL_SETUP.md |
| 5 | **A writable workspace folder** | Holds files, memory and the plan | Created automatically (`./workspace`) |

Not needed: pip packages, internet access (except for the web tools), or any account.

### B. In this repo (already built)

| # | Component | File | Why it's mandatory without a key |
|---|---|---|---|
| 1 | Provider-neutral message format | `core/messages.py` | Lets the same loop and tools work with any model |
| 2 | **Local backend** (Ollama + OpenAI-compatible) | `backends/local.py` | Without it, the only model is a paid API |
| 3 | **Prompt-mode tool calling** | `backends/local.py` (`parse_prompted_tool_calls`) | Many small or older models have no native tool calling. This reads tool calls from a JSON block in plain text instead, so any instruction-following model works |
| 4 | Auto-detect tool support | `LocalBackend.chat` (`tool_mode="auto"`) | Switches to prompt mode automatically when the server reports "does not support tools" |
| 5 | **Agent loop** with guards | `core/agent.py` | The think → act → observe cycle. Never runs cut-off tool calls, stops repeated identical calls, rolls back if the model fails, and can be stopped |
| 6 | **Context trimming** | `Agent._trim_history` | An 8k-token model overflows on long sessions. Old tool outputs are shortened first (local models only; Claude's history is never edited) |
| 7 | **Tool registry + argument validation** | `tools/registry.py` | Local models make more argument mistakes. Clear errors ("unknown argument 'pth' (valid: path…)") let them fix the call |
| 8 | **Tool profiles** | `tools/profiles.py` | All 80 tool descriptions take about 6k tokens, which would fill an 8k context. Profiles send 7–23 tools instead |
| 9 | **Tool suite** (78 tools, stdlib only) | `tools/builtin/*.py` | What the agent can do. See [04_TOOLS.md](04_TOOLS.md) |
| 10 | **Key-free web search + knowledge** | `tools/builtin/web.py`, `knowledge.py` | DuckDuckGo/SearXNG, Wikipedia, arXiv, Open-Meteo weather and a dictionary: all keyless |
| 11 | **Local document search** (BM25) | `tools/builtin/documents.py` | Searches your files without an embeddings API or model, and keeps context small |
| 12 | **Long-term memory** | `tools/builtin/memory.py` | Durable facts go into a JSON file instead of the small context window |
| 13 | **Security layer** | `security/` (guards, netguard, redact, xmlsafe) | No vendor-side safety filter sits in front of a local model. See [07_SAFETY_AND_DIAGNOSTICS.md](07_SAFETY_AND_DIAGNOSTICS.md) |
| 14 | **Safety drills** | `diagnostics/` | Prove the security layer holds: `python -m hybrid_agent diagnose` |
| 15 | **Output and size limits** | `ToolRegistry.execute`, `shell.run_process`, `security/guards.py` | One large result could fill a small context or exhaust memory |
| 16 | **Config with key-free defaults + validation** | `core/config.py`, `.env.example` | Default settings never require a key; typos fail with a clear message |
| 17 | **Doctor** | `cli/doctor.py` | Separates "required" from "optional" failures, so you can tell why the agent won't start |
| 18 | **Transcript logs** (secrets redacted) | `core/agent.py` → `logs/*.jsonl` | Smaller models fail more often, and the logs show where |
| 19 | **Scripted/canned backends + offline tests** | `backends/scripted.py`, `tests/` | Test everything, including councils and the GUI, without a model or the network |

Optional but key-free: the **council** (`council/`, [05_COUNCIL.md](05_COUNCIL.md)), **personas with faces** and the
**GUI** (`personas/`, `gui/`, [06_GUI_AND_PERSONAS.md](06_GUI_AND_PERSONAS.md)).

---

## Limits of running without a key

- **Smaller models are less reliable.** A 7B model handles simple multi-step tasks well
  and long, complex plans less well. A 14B–32B model is much better if your hardware can run it.
- **Speed depends on your hardware.** With CPU only, expect a few tokens per second.
- **Web search via DuckDuckGo is best-effort.** It can rate-limit you. Run your own
  [SearXNG](https://docs.searxng.org/) and set `SEARXNG_URL` for reliable search.
- **Context is small.** `LOCAL_NUM_CTX=8192` by default. Raise it if you have the memory.
