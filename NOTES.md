# Build notes

A log of what was built, the decisions behind it, and how it was checked.

## Goal

Build a suite of tools for an AI agent that uses **Claude** and a **local model**, and
build and document **everything the agent needs to run with no API key**.

## Guiding decision: the local model is the base, Claude is optional

I treated the local model as the foundation and Claude as an upgrade added on top.
That way the no-key requirement holds by construction: the default configuration never
touches a key, and Claude only adds things. Analogy: a house wired for mains power
(local) with an optional solar panel (Claude). It runs fully without the panel.

## What was built, in order

1. **Project skeleton**: `hybrid_agent/` package, `tests/`, `docs/`; git initialised.
2. **`messages.py`**: provider-neutral `Message`, `ToolCall`, `LLMResponse`.
   - `Message.raw` keeps Claude's original content blocks so thinking blocks can be sent back unchanged (the API requires this).
3. **`config.py`**: environment and `.env` settings, all defaults key-free. Includes a small `.env` parser so no `python-dotenv` dependency is needed.
   - *Bug found and fixed:* inline `# comments` in `.env` were being read into values. The parser now strips them, keeps `#` inside quoted values, and has a test.
4. **`backends/base.py`**: the `Backend` interface and the `BackendUnavailable` error that drives fallback.
5. **`backends/local.py`** (the key-free core):
   - Ollama `/api/chat` and OpenAI-compatible `/v1/chat/completions`, using `urllib` only.
   - Native tool calling, **plus prompt-mode tool calling** for models without it (tools described in the system prompt, JSON blocks parsed from the reply; also accepts a bare JSON object, because small models often drop the code fence).
   - `tool_mode=auto` switches to prompt mode when the server reports the model doesn't support tools, and remembers that for the session.
   - Friendly errors: "server unreachable → run `ollama serve`" and "model not found → run `ollama pull`".
   - `complete()` helper for one-shot delegation.
6. **`backends/claude.py`** (optional): official `anthropic` SDK with a manual tool loop.
   - `claude-opus-5-5`, effort `medium` (configurable), adaptive thinking left at its default (`budget_tokens` is never sent; current models reject it).
   - Server-side refusal fallback enabled by default (`fallbacks="default"`, beta `server-side-fallback-2026-07-01`). Turn it off with `CLAUDE_FALLBACKS=0`.
   - Parallel tool results are merged into one user message, as the API requires.
   - Auth, rate-limit, connection and 5xx errors raise `BackendUnavailable` so the router can fall back. 400s are re-raised so request bugs stay visible.
7. **`backends/router.py`**: tries Claude first and falls back to the local model.
8. **`backends/scripted.py`**: canned replies for tests and the `--backend scripted` smoke demo.
9. **`tools/registry.py`**: `Tool`, `ToolRegistry` (decorator API), `ToolContext`, minimal JSON-schema validation, approval gate, exception capture, and output truncation. Tool specs are sorted so requests stay prompt-cache friendly.
10. **`safety.py`**: workspace path fencing (blocks `..` and symlink escapes) and a blocklist for destructive shell commands.
11. **Tools** (16 total, all stdlib):
    - `filesystem.py`: read_file, write_file (asks before overwriting), edit_file, list_dir, find_files, search_text
    - `execution.py`: run_shell, run_python (approval + timeout)
    - `web.py`: fetch_url (HTML → text), web_search (SearXNG or DuckDuckGo HTML, no key)
    - `memory.py`: remember, recall, forget (JSON file, atomic writes)
    - `utilities.py`: calculator (AST-based, no `eval`), current_time, update_plan, delegate_to_local
12. **`agent.py`**: the think → act → observe loop with a step limit, usage totals, event hooks, and JSONL transcript logs.
13. **`doctor.py`**: readiness check that separates *required* (Python, local server, model pulled, workspace) from *optional* (Ollama CLI, anthropic SDK, Claude key, SearXNG). Exit code 0 means it can run key-free.
14. **`cli.py`**: REPL plus one-shot mode, and `doctor` / `tools` subcommands; flags for backend, model, workspace and auto-approve.
15. **Tests** (`tests/test_agent.py`, 21 tests, stdlib `unittest`): tools, sandbox escape, validation, approval refusal, memory, calculator safety, truncation, HTML extraction, `.env` parsing, the agent loop, the step limit, router fallback, prompt-mode parsing, Claude message conversion, and **fake Ollama and OpenAI HTTP servers** that exercise the real local backend end-to-end, including the automatic switch to prompt mode.
16. **Docs**: README, `docs/OFFLINE_REQUIREMENTS.md`, `docs/LOCAL_MODEL_SETUP.md`, `docs/ARCHITECTURE.md` (Mermaid diagrams), `docs/TOOLS.md`, `.env.example`, `pyproject.toml`, `requirements-claude.txt`.

## Verification (what was actually run)

| Check | Result |
|---|---|
| `python3 -m unittest discover -s tests` | **21/21 pass** |
| `--backend scripted -p demo` | Loop ran current_time, calculator and write_file; file created |
| `doctor` with no Ollama running | Correctly reports FAIL on server/model, PASS on Python/workspace, exit 1 |
| `anthropic` 1.17.0: signature check | `messages.create` accepts `output_config`, `tools`, `system`; `beta.messages.create` also accepts `fallbacks` and `betas`; all 4 error classes exist |
| `--backend claude` with a bogus key | Real API returned 401 → router logged it and fell back to the local backend |
| Real local model run | **Not done.** The build sandbox's network policy blocked downloading Ollama (HTTP 403). The fake-server tests cover the same HTTP protocol; run `doctor` and then a prompt on your own machine to confirm |
| Real Claude tool-use run | **Not done** (no key in the build environment) |

## Known limitations / next steps

- **No streaming** to the terminal yet. Answers appear when complete.
- **No context compaction** for long local sessions. Use `/reset`, or raise `LOCAL_NUM_CTX`.
- **`run_shell` is not a true sandbox.** Use a container or VM for untrusted tasks.
- DuckDuckGo HTML scraping can break if they change their markup. SearXNG is the robust option.
- Possible additions: an MCP client so the agent can use MCP servers, a vector memory using local embeddings (Ollama `/api/embed`), and a planner/worker split where Claude plans and the local model executes each step.
