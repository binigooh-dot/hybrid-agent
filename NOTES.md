# Build notes

A log of what was built, the decisions behind it, and how it was checked. Newest session first.

---

## Session 5b: first run on real Windows (GitHub Actions) - v1.1.1

The first GitHub Actions run: **Linux passed everything. Windows failed 4 tests**, real bugs that Linux and
Wine hadn't shown. macOS sat in GitHub's queue and never started, which blocked the release step, so the
`v1.1.0` release stayed empty and the README pointed people to downloads that didn't exist.

| Found on real Windows | Fix |
|---|---|
| `rm -rf /etc/passwd` and `cp evil /etc/hosts` were not recognised as touching protected paths: `/etc` doesn't exist on Windows, so it was never resolved to a full path (`C:\etc`) and the comparison silently failed | Protected paths are always resolved (missing ones too), and drive-less rooted paths (`/etc/...`) count as absolute on every OS |
| `find_files` returned `src\m.py` | Tool output always uses `/` (files, search, document index, archives, backup index) |
| `docs/FILE_MAP.md` order differed: Windows compares paths case-insensitively | Sorted by the `/` path text |
| The release waited for macOS, which never got a runner | macOS is its own job and attaches its zip whenever it finishes. The release needs Windows + Linux and checks both zips are present |

Also:
- **New `tests/test_docs.py`:** every markdown link, every repo path in backticks, every link in the guide,
  the download file names and the workflow's scripts must exist. It found docs naming the faces module by
  a short path that pointed at the top-level personas folder (your own persona files) instead of
  `hybrid_agent/personas/faces.py`.
- **README:** links to the latest release for downloads.
- **Run #5 annotations** (all fixed):
  - macOS was never picked up ("not acquired by Runner… capacity constraints for macOS arm64"). macOS now
    has its own workflow (`macos.yml`, on releases and on demand) on the Intel pool (`macos-15-intel`); the
    build also runs on Apple silicon via Rosetta 2. Its queue can no longer fail or block the main build.
  - "Node.js 20 is deprecated": moved to checkout@v5, setup-python@v6, upload-artifact@v6,
    download-artifact@v7 and action-gh-release@v3 (each verified from its action.yml). A test keeps it that way.
  - "ubuntu-latest will migrate to Ubuntu 26": pinned `ubuntu-24.04`, so the Linux download (which needs
    a glibc at least as new as the build machine's) keeps working on more systems.
- **Windows dry run:** the whole suite ran on Windows Python 3.12 under Wine before pushing. The only
  failures were two Wine-only differences (no git in Wine; Wine's symlinks), both of which pass on the real
  Windows runner.

---

## Session 5: desktop app (.exe), control panel, task scheduler, going online, crisper faces - v1.1.0

**Request:** a self-hosted .exe suite for the GUI and a control panel, where all files and a local model live
together, and where tasks can be queued or scheduled for agents. It should be online so agents can reach sites
like Wikipedia (explain first if that doesn't work). Also research and refine the GUI, and make the faces
crisper and tighter.

### 0. Online check first (as asked)

The first live test **failed**. This cloud workspace's network refused Wikipedia and DuckDuckGo. That was
explained before continuing, and the user widened the network setting. It also exposed a real weakness:
the web tools did their own DNS lookup as a safety check, so on networks where only a proxy can resolve names,
nothing worked.

| Found live | Fix |
|---|---|
| Proxy-only networks: every site "can't resolve" | `netguard`: if the URL goes through a configured proxy (env or OS settings) and the name can't be resolved locally, the proxy resolves it. Names are still checked: IP literals, `localhost`, `*.internal`, `*.local`, metadata hosts |
| Wikipedia API: HTTP 429 | Honest Wikimedia-style User-Agent with your contact (`AGENT_CONTACT`; identified bots get 200 requests/min, unidentified ones 10). Retry-After honoured. If the API is busy, read the article page or find articles via a public search engine |
| DuckDuckGo refuses honest programs (HTTP 202) | Search chain SearXNG → DuckDuckGo → Marginalia (a free API made for programs) → Wikipedia, naming the provider that answered. **Never** pretend to be a browser. Bing's RSS works but its terms forbid this use, so it isn't used |
| arXiv used `http://` | https |
| Intermittent TLS handshake timeouts | One retry for network blips; search providers capped at 10 s |

Verified live: Wikipedia, web search, weather, arXiv, RSS feeds, link extraction.

### 1. Portable home folder (`core/home.py`)

One folder next to the app holds `settings.env`, `workspace/`, `personas/`, `logs/`, `tasks/`, `models/` and
`runtime/`. Settings, tasks, the engine and models are added to the protected paths. The Control panel can
edit a fixed list of settings; auto-approve and "sandbox off" are deliberately not editable from the browser.

### 2. Task queue + scheduler (`tasks/`)

Schedules: manual, once, every N minutes, daily, weekdays. One task runs at a time, waiting while you chat.
Missed runs run once at startup. Full run history; each result is saved as Markdown.

**Unattended safety:** the default permission is *look, don't touch* (read and network tools only).
*Ask me first* uses the normal approvals, and nobody answering means Deny. Tests cover schedule maths,
persistence and corruption, the one-at-a-time rule, pause, history, path-safe result reading, the safe
permission and the HTTP API.

Bug found by a test: `due()` compared against a clock with the microseconds cut off, so a task due at
09:00:00.4 waited for the next poll. Fixed.

### 3. Control panel + model engine (`runtime/ollama.py`)

Install Ollama from ollama.com **into the home folder** (Windows zip ≈1.6 GB, Linux `.tar.zst`), start and
stop it (127.0.0.1 only), and pull, switch or delete models (stored in `home/models` via `OLLAMA_MODELS`).
Progress streams to the GUI. Zip-slip protection on the engine archive. Online check, settings, storage and Quit.

**End-to-end, for real:** the engine downloaded from ollama.com, started, and pulled `qwen2.5:1.5b` (986 MB).
A queued task ran through the scheduler on that local model, called `wikipedia_summary` against live
Wikipedia, and answered "Ada Lovelace was born in 1815" in 31 s on CPU. The packaged Linux app then did the
same with a scheduled weather task, re-armed it for the next day, and Quit stopped the GUI, scheduler and engine.

### 4. GUI research and refinement; crisper faces

Research applied:
- Lead with the one "is everything OK?" signal, with details on demand. Red only for real problems.
- Schedulers as a list plus detail, with dropdown recurrence, next run and Run now.
- Box-drawing characters only join up if the font draws them full-height, and fonts differ.

Changes:
- **Top bar health pill:** *Ready · model* / *Engine stopped* / *Demo mode*. Clicking it opens Control.
- **Grouped tabs:** Work · Library · System.
- **New Tasks and Control tabs**, and a first-run banner that points to Control.
- **Faces redrawn** with box-drawing and block characters:
  - outlines ╭─╮ ┌─┐ ┏━┓ ╔═╗ and eyes ● ○ ◉ ◕ ■ •;
  - mouths open as blocks (╶▄╴ ▐█▌), eyes glance (◔), thought dots rise (∙ ° ○);
  - an engine "face" for the Control tab.
- **Bundled font:** an 18 KB subset of JetBrains Mono, licence included. It was measured in Chromium at
  line-heights 1.0 to 1.32 and joins at all of them, so line-height 1 is used. The system font showed gaps.
- **Font guarantee:** the integrity check and a test ensure every face character is in the font.
- **Legacy faces:** old ASCII persona files upgrade automatically.

### 5. The .exe (`packaging/`, `scripts/build_exe.py`)

PyInstaller one-folder build with icon and Windows version info. Inside it, `sys.executable` is the app, so a
hidden `--hybrid-python` mode (`core/pyexe.py`) serves the regex worker, the sandbox limiter and `run_python`.
`run_python` prefers a real Python installed on the computer.

The **Windows .exe was built on Linux**: official Windows Python 3.12 (nuget) + PyInstaller under Wine 9.
Testing it under Wine found real Windows bugs, all fixed:

| Found | Fix |
|---|---|
| Personas failed to load: Windows reads files in cp1252 by default | `encoding="utf-8"` on every text file operation (an AST rewrite, with its slips caught by tests and mypy), and a test that keeps it that way |
| No time-zone data on Windows | `tzdata` dependency on Windows, bundled into the exe |
| Child Pythons printed in cp1252 | `-X utf8` for the regex worker and `run_python`; the built-in Python honours it |
| A timed-out command left its children running on Windows | `taskkill /F /T` ends the whole tree (verified: 0 processes left) |
| "Press Enter to close" also fired inside helper processes (they rewrite argv) | Decided before anything runs |
| Wine 9 lacks `CopyFile2` (Python 3.12 file copies) | Detect Wine and use Python's older copy method. Real Windows is unaffected |
| A drill copied source files the packaged app doesn't have | It creates decoy files instead |

Results:
- Linux binary: 39/39 drills and the real-engine end-to-end test.
- Windows exe under Wine: 39/39 drills, online check 4/4, council, a scheduled task (drills 39/39) and Quit,
  all driven from a real browser.
- `.github/workflows/build.yml` runs the tests, drills and builds on **real** Windows, macOS and Linux, and
  publishes a release when a version tag is pushed.

### 6. Verification

- Tests: 158, all passing. New: `test_tasks.py`, `test_app.py`, plus portability, font, proxy, etiquette and
  fallback tests.
- `health_check.py`: 10/10.
- `.exe` size: 23 MB unpacked, 11 MB zipped (Linux build similar).

---

## Session 4: hard safety, ASCII faces, GUI refinement, release 1.0.0

**Request:** hard safety features protecting the user's system and data, and the files the hardware and the
agents need; optimise and trim the code without losing integrity; replace the persona faces with cheap,
recognisable ASCII faces with expressions and animations; refine the GUI; test it; package and ship.

### 1. Hard safety (new: `security/sandbox.py`, `protected.py`, `backup.py`, `audit.py`)

Before this session the defences were *policy* (the agent's own code refusing things). Now the **operating
system** enforces them too, so a cleverly-written command can't talk its way past.

| Layer | What it does | Verified |
|---|---|---|
| Kernel sandbox | bubblewrap / sandbox-exec: system read-only, home replaced by an empty folder, private `/tmp`, only the workspace writable, `.agent/` read-only | live: `touch /etc/x` fails, `ls ~` empty, a fake API key isn't visible |
| Kernel limits | CPU, memory, file size, open files, no core dumps, for the command and every child. Set by a tiny exec launcher, not `preexec_fn` (which can deadlock with threads) | 600 MB allocation refused; file capped at 1 MB |
| Env scrubbing | secrets, `LD_PRELOAD`, `GIT_SSH_COMMAND`, the whole `GIT_CONFIG_*` family… | drill + unit test |
| Protected paths | OS/boot/firmware/devices, keys and shell configs, the agent's own package | 30+ commands refused, no false positives |
| Hardware guard | firmware/BIOS writes, partitioning, kernel modules, sysctl, services, accounts, firewall | blocklist drill |
| Undo | every overwrite/edit/move/delete backed up first; delete = trash; `list_backups` / `restore_backup` tools; GUI Restore button | drill + unit tests + browser test |
| Disk guard | refuse writes below `AGENT_MIN_FREE_MB` or 2 % of the disk | drill |
| Safe mode | `AGENT_SAFE_MODE=1` = read/network tools only | drill + unit test |
| Audit log | every write/execute call, redacted, to `logs/audit.jsonl` | drill + unit test |
| Integrity manifest | SHA-256 of every package file in a release; doctor/diagnose/GUI flag changes | drill + unit test; verified on the installed wheel |

Problems found and fixed along the way:
- git broke inside the sandbox because the secret filter dropped `GIT_CONFIG_KEY_0` but not `GIT_CONFIG_COUNT`.
  The whole family is now dropped, which also closes an fsmonitor injection route.
- git commit failed because this machine signs commits through a helper the sandbox hides. The agent now
  commits with signing off: it must never sign as you.
- **Found while shipping:** temp folders were exempt from the protected-path check (needed on macOS, where
  temp lives under `/private/var`), but that also exempted the agent's own files. An agent installed under a
  temp folder could therefore be given its own code as a workspace. Now only the system paths are exempt; a
  regression test was added.

**Drills: 29 → 39, all passing.**

### 2. ASCII faces with animation

`hybrid_agent/personas/faces.py` was rewritten: 7 lines × 16 columns of text, built from fixed menus (7 hair, 3 head
shapes, 6 eyes, 6 noses, 3 mouths, glasses/beard/earrings/freckles, 8 colours). There are 7 expressions;
*speaking* and *thinking* have 4 frames each, and idle faces blink. The browser runs one shared 230 ms timer
for all faces and only swaps text, so the CPU cost is negligible.

| | Before (SVG) | After (ASCII) |
|---|---|---|
| `faces.py` | 230 lines | 128 lines |
| Face payload, 3 personas | 41,785 bytes | 5,777 bytes (−86 %) |
| Rendering | `innerHTML` of sanitised SVG | `textContent` only, so nothing can be injected |
| Animation | CSS on SVG parts | real frames: mouth, darting eyes, thought dots, blink |

The `image` field (portrait groundwork) was removed; old persona files that still contain it load fine.

### 3. GUI refinement

- **Council:** three numbered steps (ask / who's in the room / how they decide) with example questions,
  tap-to-pick faces, a ★ chair and protocol cards. The stage has animated faces with a status line and vote
  badge; a conversation-style Discussion feed; and a Decision card with animated vote bars.
- **Chat:** tool use folded into "🔧 used N tools"; suggestion chips; persona face in the header.
  - Fixed a race: a fast reply could arrive before the "thinking" bubble existed, leaving it behind.
- **Personas:** a face builder (menus, toggles, swatches, live animated preview); the id is suggested from
  the name; rarely used fields are under *Advanced*.
- **Safety tab:** status cards, an undo history with Restore, drills and setup check. A coloured dot on
  the tab shows the overall state.
- **Approval dialog:** risk badge, *exactly* what will run shown on its own, full details folded away,
  focus on Deny, and a countdown bar.
- **First-run banner** when no local model is reachable.
- **Server:** routes are declared with a `@route` decorator instead of if-chains, plus `/api/safety`,
  `/api/restore`, a 30 s meta cache, and the portrait route removed.

### 4. Optimisation and trimming

| | Before | After |
|---|---|---|
| Build a registry | 0.31 ms | 0.005 ms (tool catalogue cached) |
| Build all 8 profiles | 2.7 ms | 0.24 ms |
| `faces.py` / `server.py` | 230 / 449 lines | 128 / 424 |

Total Python grew from 7,230 to 8,262 lines. The ~400 lines of new security modules and ~170 lines of new
drills outweigh the trimming; the GUI files grew for the new features (steps, builder, safety centre).

### 5. Verification

- 133 tests, all passing, including a new `tests/test_security.py` (sandbox, protected paths, backups,
  audit, manifest, safe mode) and updated GUI tests (`/api/face`, `/api/safety`, `/api/restore`).
- `health_check.py`: 10/10 checks pass. They are tests, ruff, mypy, bandit, vulture, vermin, radon,
  drills, coverage (80 %) and the real-browser test.
- The browser test now also checks that the faces really animate and that Restore really restores a file.

### 6. Release 1.0.0

`scripts/build_release.py` does four things:
1. writes the integrity manifest;
2. builds the wheel and sdist into `dist/`;
3. writes `SHA256SUMS`;
4. removes the manifest from the source tree again.

The wheel was installed into a clean venv and tested there:
- `hybrid-agent -p demo`, `council` and `diagnose` all work.
- The manifest verifies (71 files).
- The GUI serves `/` and `/guide` and refuses requests without the token.

**Found by this test:** the `hybrid-agent` console command crashed on start, because the entry point named
the `cli.main` module instead of the `main()` function. Fixed.

---

## Session 3: GUI, personas with faces, knowledge suite, full diagnostic, cleanup, upscale

**Request:** a browsable HTML guide ("Agent Builder knowledge suite"); groundwork for a GUI with a council
of 2–3 persona agents that have faces; a full diagnostic with simulated critical events; a full code-health
check by any means; then organise, clean up, and upscale.

### 1. Full diagnostic: simulated critical events (fire drills)

Built `hybrid_agent/diagnostics/`: 29 drills in 9 areas, each in a throwaway sandbox. While they run, a
**process tripwire** refuses destructive subprocesses and a **network tripwire** blocks and records every
non-loopback connection, so the drills themselves can never cause harm. They ran against the code *before*
fixing anything:

**Before: 14/29 passed, 5 critical failures. After: 29/29, none.** The full table is in
`docs/07_SAFETY_AND_DIAGNOSTICS.md`. What the simulations exposed, and the fixes:

| Found | Fix |
|---|---|
| A repo's `.git/config` (fsmonitor, external diff) **ran commands** when the agent used git | git runs with every program-launching setting overridden, plus `--no-ext-diff --no-textconv` and a cleaned environment |
| Web tools could reach **cloud metadata (169.254.169.254)**, your **LAN**, and **follow redirects** there | `security/netguard.py`: resolve-and-check before connecting; every redirect re-checked; two policies (public / local) |
| **17 of 34** destructive command variants slipped past the blocklist | Rewrote it as a tokenising checker: any recursive delete with an absolute, `~`, `$HOME`, `..` or wildcard target is refused; Windows forms, `find -delete`, recursive chmod… 34/34 with zero false positives on 8 safe commands |
| `/` or home accepted as the workspace | `validate_workspace` at every entry point |
| `(a+)+$` **froze the whole process for 345 s**. Even the drill's timer couldn't fire, because the regex engine holds Python's GIL | Risky-shaped regexes run in a child process killed after 5 s; normal ones stay in-process. Useful nested patterns like `[a-z]+(\.[a-z]+)*` still work |
| A corrupt `memory.json` was **silently wiped** on the next save | Moved aside to `memory.json.corrupt-<time>` |
| API keys were written to **session logs** in plain text | `security/redact.py` applied to logs, council transcripts and the GUI event feed |
| A 300 MB file read used 744 MB of RAM; a 200 MB output flood used 600 MB | Streamed reads; output drained into bounded buffers (1 MB kept) |
| Timeouts left **orphan child processes** | New process session; the whole tree is killed |
| No zip-bomb limit; big downloads silently truncated | 1 GB / 20,000-entry archive limit; downloads error cleanly with no partial file |
| A model repeating one call ran it 30 times | Loop guard: the 4th identical call in a row is refused |

Two of my own drills had bugs (one triggered its own trap; one miscounted). Both were fixed and noted, so
the results are honest. The drills now run inside the test suite.

### 2. Code health "by any means": tools used and results

| Tool | Initial | Final |
|---|---|---|
| ruff (broad rule set incl. security) | 113 findings | clean; config committed in `pyproject.toml` |
| mypy | 23 errors (later 54 with new code) | clean |
| bandit (medium+) | 13 issues | clean; each deliberate case marked `# Reviewed (Bxxx): reason` |
| vulture (dead code) | 4 | none |
| radon (complexity) | 2 functions rated D | none worse than C (`LocalBackend._chat` split into per-provider adapters; `doctor` split into check functions) |
| vermin (min Python) | flagged `tomllib` | 3.10 (that import is guarded) |
| coverage | measured | reported by `scripts/health_check.py` |
| Python 3.11 / 3.12 / 3.13 | | all tests pass |
| Playwright + Chromium | n/a | GUI driven end to end; no JS errors; no horizontal scroll at phone width |

Real bugs these surfaced (beyond style): the file-map test broke whenever a tool left a stray file (now
lists git-tracked files only); `council.save()` would crash with logging off; a `RecursionError` from a tool
name shadowing a guard function (introduced and caught this session); `doc 01` had a duplicated stale table
from a session-2 edit that matched `---` inside a table; an `xml_query` variable reuse bug flagged by mypy.

### 3. Personas with faces + GUI groundwork (working, not just scaffolding)

- `personas/`: Persona model (JSON), presets **Sage** (chair), **Vex** (skeptic), **Nova** (researcher), and
  `faces.py`, a procedural SVG face generator (8 hair styles, 3 face shapes, glasses, beard, earrings,
  freckles, blush) with **7 expressions**. All inputs are validated, so it's safe to inline.
- Council integration: `Council.from_personas`, `--personas sage,vex,nova`, `"personas": [...]` in configs.
- `gui/`: **Agent Studio**, a stdlib HTTP server and a vanilla-JS single-page app, with no CDN, so it works offline.
  Council stage with live expressions (thinking → speaking → happy/concerned by vote), chat as a persona,
  persona editor with live face preview, tool browser, safety centre, and Allow/Deny approvals (silence = deny),
  Stop button (cooperative cancel + rollback). Security: 127.0.0.1 only, per-launch token, Host/Origin checks,
  strict CSP, text-only model output, 1 MB bodies, whitelisted static files.
- Avatar roadmap in `docs/06_GUI_AND_PERSONAS.md`: portraits via `"image"`, per-expression images, TTS voices, lip-sync, streaming.

### 4. Agent Builder Knowledge Suite

`docs/agent_builder_suite.html`: one self-contained file (open it from disk), generated from the code by
`scripts/gen_knowledge_suite.py`, also served live at `/guide` in the GUI. Sections: overview diagrams, quick
start, **tool explorer**, **profile builder** (context-cost gauge, generated profile string), **council
designer** (config JSON + command + cost estimate), protocols and roles, persona gallery with expressions,
safety centre (layers + drills + latest results), setup and models, glossary with analogies.

### 5. Upscales

- **Context trimming** for local models: old tool outputs are shortened when the history outgrows ~60% of
  the context; recent ones stay whole. Never applied to Claude (its API needs an unedited history).
- **Config validation** with clear startup errors; `Config.context_chars()`.
- **Cooperative cancel** (`Agent.cancel`, `Council.cancel`) used by the GUI Stop button.
- `registry.group()` replaces 16 lambda helpers; `reg[name]` / `reg.tools()` replace optional lookups.
- `doctor` gains workspace-safety and persona checks.
- `scripts/health_check.py` runs every check with one command.

### 6. Organisation and cleanup

- New `security/` package: every protection in one place (moved out of `core/`).
- New `diagnostics/`, `personas/`, `gui/` packages; `personas/` folder for your own files; docs 06 and 07.
- Every file labelled, including HTML/CSS/JS; `docs/FILE_MAP.md` regenerated; build artefacts git-ignored.

### 7. Verification (what was actually run)

| Check | Result |
|---|---|
| Full test suite | **all pass** (3.11, 3.12, 3.13) |
| Safety drills | **29/29** |
| ruff / mypy / bandit / vulture / vermin / radon | clean / clean / clean / none / 3.10 / ≤ C |
| GUI in headless Chromium: council vote, persona chat, persona editor, approval Deny, tools, doctor, phone width | **no errors** |
| GUI via the real CLI (`gui --backend scripted`): index 200, API without token 401, guide 200 | as expected |
| Live online services (Wikipedia, arXiv, Open-Meteo, DuckDuckGo) | **not verified**: blocked by this build container's network |
| A real local model or Claude doing a task | **not verified**: no Ollama download allowed here, no API key |

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
