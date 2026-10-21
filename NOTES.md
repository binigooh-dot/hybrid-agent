# Build notes

A log of what was built, the decisions behind it, and how it was checked. Newest session first.

---

## Session 2: code review, large tool suite, council groundwork, reorganisation

**Request:** check the code, add a large suite of tools, lay the groundwork for a council of agents,
and organise and label all files.

### 1. Code review: problems found in v0.1 and fixed

| # | Problem | Effect | Fix |
|---|---|---|---|
| 1 | `Agent.run` left the user message (and any half-finished tool exchange) in the history when the model backend failed partway | The next attempt sent a malformed conversation | `run()` checkpoints the history and rolls it back on any exception (`core/agent.py`) |
| 2 | Tool calls were executed even when the model hit its **output limit**, so their arguments could be cut off | Half-written files, garbage commands | When `stop_reason == "max_tokens"`, calls are not run; each gets an error result telling the model to retry with smaller input. Every call still gets a result, as Claude requires |
| 3 | `doctor` matched model names too loosely (`qwen2.5` passed when only `qwen2.5:14b` was installed) | "Ready" reported, then a 404 at runtime | `model_available()`: an exact match, or `:latest` for tag-less names |
| 4 | `search_text` scanned binary files | Garbage matches, wasted context | Files with a NUL byte in the first 8 KB are skipped (`is_binary`) |
| 5 | Arguments the tool doesn't accept (e.g. a typo) only produced a Python `TypeError` traceback | Small models couldn't tell what to fix | Validation now says `unknown argument 'pth' (valid: path, offset, limit)` |
| 6 | Log files were named by the second, so two agents started together shared one file | Mixed-up transcripts (would affect every council) | Log name = time + agent name + random suffix |
| 7 | The memory file and the y/N prompt weren't safe with several agents at once | Possible lost writes and tangled prompts | A shared `FILE_LOCK` around memory/index writes; prompts serialised with a lock |
| 8 | Every tool's description is sent on every request | With 78 tools that's about 6k tokens, which would fill a local model's context | **Tool profiles** (`tools/profiles.py`): 7–23 tools for local models, `full` for Claude |
| 9 | Removing `delegate_to_local` reached into a private dict | Fragile | `ToolRegistry.unregister()` |
| 10 | `check_syntax` had a confusing XML condition; tar extraction needed a `filter=` option missing from some older Python 3.10/3.11 patch releases | Wrong file types checked; a crash on those Pythons | Simplified the condition; added a fallback (entries are validated first anyway) |
| 11 | `xml_query` printed `{}` / double spaces for elements without attributes | Messy output for the model | Attributes are rendered properly |
| 12 | `--backend scripted` didn't affect council members that name their own backend | No way to test a council config before downloading models | `--backend scripted` is now a **dry run** for any config |

### 2. Reorganisation and labels

- The code is split into labelled layers: `core/`, `backends/`, `tools/` (with `builtin/`), `council/`, `cli/`.
  Files were moved with `git mv`, so their history is kept.
- **Every Python module's docstring starts with a `[LAYER / name]` label** (e.g. `[TOOLS / files]`).
  A test enforces this.
- Docs are numbered in reading order (`01_`…`05_`), with an index at `docs/README.md`.
- `docs/04_TOOLS.md` and `docs/FILE_MAP.md` are **generated** by `scripts/gen_tool_docs.py` and
  `scripts/gen_file_map.py`, and tests fail if either goes stale.
- Shared exceptions moved to `core/errors.py`, so no module needs a circular import.
- Tests are split into one file per area (`tests/test_core.py`, `test_backends.py`, `test_tools_*.py`, `test_council.py`).

### 3. Tool suite: 16 → 78 tools, 16 categories, all stdlib, none needs a key

| Category | Tools | New in v0.2 |
|---|---|---|
| files (14) | read/write/append/edit, list_dir, tree, find, search, file_info, make_dir, copy, move, delete, diff | 8 |
| shell (3) | run_shell, run_python, which | which; per-call timeout |
| code (7) | code_outline, check_syntax, run_tests, git_status/diff/log/commit | all |
| data (6) | csv_read, csv_query (filter/sort/group/aggregate), json_query, convert_data, sqlite_query, xml_query | all |
| text (9) | text_stats, regex_find, regex_replace_file, extract_entities, compare_text, encode_decode, hash_text, hash_file, generate_id | all |
| math (4) / time (3) | calculator, statistics, unit_convert (10 dimensions), convert_base / current_time (any timezone), date_calc, convert_timezone | 6 |
| web (4) / network (4) | fetch_url, web_search, extract_links, download_file / http_request, check_url, dns_lookup, check_port | 6 |
| knowledge (6) | wikipedia_search/summary, arxiv_search, weather (Open-Meteo), define_word, read_feed (RSS/Atom) | all |
| system (4) | system_info, disk_usage, env_vars (secret values hidden), python_packages | all |
| archives (3) | archive_list/create/extract (zip, tar.*; zip-slip protected) | all |
| memory (3) / documents (2) | remember, recall, forget / index_documents + search_documents (BM25 ranking, no embeddings) | 2 |
| agent (4) | update_plan, think, ask_user, delegate_to_local | think, ask_user |
| council (2) | board_post, board_read | all |

Framework additions: a **category** and **risk** label on every tool (`read < network < write < execute`),
the compact `S()` schema builder, `registry.subset()`, profile strings with `+tool` / `-tool` / `@category`,
and a test that checks every schema against its function's signature.

### 4. Council groundwork (`hybrid_agent/council/`)

- **MemberSpec** (JSON-friendly): name, role, backend (`default`, `local[:model]`, `claude[:model]`, `scripted`),
  tool profile, persona, weight, max_steps.
- **Roles** (8): chair, researcher, skeptic, engineer, analyst, strategist, advocate, generalist. Each has a persona and a default tool profile.
- **Blackboard:** a thread-safe shared board, plus the `board_post` / `board_read` tools.
- **Ballots:** parses `VOTE:` / `CONFIDENCE:` lines and tallies them (weighted or majority), with ties, consensus and abstentions.
- **Protocols:** `roundtable`, `debate` (stops early on consensus), `vote` (the chair proposes options if none are given, and breaks ties), `critique` (draft → critique → revise).
- **Council / Session:** builds one Agent per member, runs members in parallel threads (`workers`), lets failed members
  sit out, raises `CouncilError` if no one answers, falls back to raw positions if the chair fails, and saves Markdown + JSON transcripts.
- **CLI:** `python -m hybrid_agent council -p ... --protocol --rounds --options --council-config --workers`.
- **Examples:** `examples/council.example.json` (Claude chair + mixed local models), `council.local-only.json`, `council_demo.py`.
- Documented in `docs/05_COUNCIL.md`, including the hardware limits and next steps (an `ask_council` tool, streaming, adaptive rounds).

### 5. Verification (what was actually run)

| Check | Result |
|---|---|
| `python3 -m unittest discover -s tests -t .` | **87/87 pass** (all offline) |
| Every tool's schema matches its Python signature | Pass (test) |
| Every Python file has a `[LAYER]` label; generated docs are current | Pass (tests) |
| Web/network tools against a **local** HTTP server (fetch, links, download, POST, check_url, check_port, dns) | Pass |
| Local backend against fake Ollama and OpenAI-compatible servers, including the auto-switch to prompt mode | Pass |
| All 4 council protocols, failing members, a failing chair, all members down, 3 parallel workers, config load and save | Pass |
| CLI: `tools`, `--backend scripted -p demo`, `council --backend scripted` with the mixed config | Ran correctly |
| `examples/custom_tool.py --demo`, `examples/council_demo.py` | Ran correctly |
| Live calls to Wikipedia / arXiv / Open-Meteo / dictionaryapi / DuckDuckGo | **Not verified.** This build container's network blocks these hosts. Their response *parsers* (RSS/Atom, HTML) are unit-tested; try `weather`, `wikipedia_summary` and `arxiv_search` on your machine |
| A real local model or Claude doing a full task | **Not verified** (no Ollama download allowed here, no API key). Run `doctor`, then a prompt and a council, on your machine |

---

## Session 1: initial build

**Request:** a suite of tools for an agent that uses Claude and a local model, with notes on everything,
and everything needed to run without an API key.

**Guiding decision:** the local model is the base and Claude is an optional upgrade, so the no-key
requirement holds by construction. Analogy: a house wired to the mains (local), with an optional
solar panel (Claude).

Built: provider-neutral messages; key-free config with a `.env` loader (bug found and fixed: inline
`# comments` were being read into values); a local backend (Ollama + OpenAI-compatible, native and
prompt-mode tool calling, auto-detection); an optional Claude backend (`claude-opus-5-5`, effort
`medium`, adaptive thinking left at its default, thinking blocks replayed unchanged, parallel tool
results merged, server-side refusal fallback, errors mapped to `BackendUnavailable`); the router;
a scripted backend; the tool registry with validation, approval and truncation; the safety layer;
16 tools; the agent loop with JSONL logs; `doctor`; the CLI; 21 offline tests; docs.

Verified then: 21/21 tests, the scripted demo, `doctor` without a server, the `anthropic` 1.17.0
signatures, and the Claude → local fallback with a bogus key (the real API returned 401).

---

## Known limitations / next steps

- **No streaming** to the terminal yet; answers appear when complete.
- **No context compaction** for long local sessions; use `/reset`, or raise `LOCAL_NUM_CTX`.
- **`run_shell`, `run_python` and `run_tests` are not a true sandbox.** Use a container or VM for untrusted tasks.
- DuckDuckGo HTML scraping can break if they change their markup; self-hosted SearXNG is the robust option.
- Council next steps are listed in `docs/05_COUNCIL.md` (an `ask_council` tool with a recursion guard, streaming, adaptive rounds, evaluation).
- Other ideas: an MCP client so agents can use MCP servers, and an optional embeddings-based memory via Ollama `/api/embed`.
