# 07 · Safety, diagnostics and code health

## Defence in depth

Analogy: a castle. A moat, then a wall, then guards at each door, then a vault. Each layer catches what
the one before misses, so no single mistake is fatal.

| Layer | Where | What it stops |
|---|---|---|
| **Workspace fence** | `security/guards.py` `resolve_in_workspace`, `validate_workspace` | `..`, absolute paths and symlinks out of the workspace; `/`, home or system folders as the workspace |
| **Approval** | `ToolRegistry.execute`, CLI y/N, GUI Allow/Deny | Shell, Python, tests, git commit, move, delete, download and overwrite run only when you say yes (silence = no) |
| **Command blocklist** | `security/guards.py` `check_shell_command` | Recursive deletes outside the workspace (`rm -rf ~/`, `rm -r -f /`, `find / -delete`…), disk formatting, fork bombs, `curl … \| sh`, power-off, Windows `del /s`… even when approved |
| **Network guard** | `security/netguard.py` | Web tools reach the public internet only. Cloud-metadata (169.254.169.254) and link-local addresses are always blocked, and every redirect hop is re-checked |
| **Resource limits** | `tools/builtin/shell.py`, `security/guards.py`, `archives.py`, `web.py` | Timeouts kill the whole process tree; output is capped at 1 MB per stream; streamed file reads; 20 MB whole-file cap; 1 GB / 20,000-entry archive cap; 50 MB download cap |
| **ReDoS guard** | `security/guards.py` + `regex_worker.py` | Regexes that could take exponential time run in a separate process that is killed after 5 s |
| **Git hardening** | `tools/builtin/code.py` | A repository's own config can't make git run programs (fsmonitor, hooks, external diff, pager, ssh, credential helpers) |
| **Safe XML** | `security/xmlsafe.py` | Entity-expansion and external-entity tricks (DTD/ENTITY declarations are refused) |
| **Loop guards** | `core/agent.py` | Cut-off tool calls never run; a 4th identical call in a row is refused; Stop rolls back cleanly |
| **Secret redaction** | `security/redact.py` | API keys, tokens, JWTs, private keys and `password=` values are scrubbed from logs, transcripts and the GUI feed |
| **Data integrity** | `memory.py`, `documents.py` | Atomic writes and a shared lock; a corrupt memory file is moved aside, never wiped |
| **GUI lock-down** | `gui/server.py` | 127.0.0.1 only, per-launch token, Host/Origin checks, strict CSP, text-only rendering of model output |

**What this is not:** a sandbox against a determined attacker. `run_shell` and `run_python` still run as
*you*. The blocklist catches mistakes and obvious attacks. For untrusted tasks, run the agent in a
container or VM and keep approval on (no `-y`).

## Fire drills

```bash
python -m hybrid_agent diagnose              # all drills + integrity checks
python -m hybrid_agent diagnose --only network
python -m hybrid_agent diagnose --json
```
Or use the GUI's **Safety** tab. Each drill simulates a critical event in a throwaway folder and checks the
defence holds. Analogy: a fire drill uses a smoke machine, never a real fire.
- Destructive commands are only ever **checked**, never executed.
- While drills run, a **process tripwire** refuses any destructive subprocess, and a **network tripwire**
  records and blocks every non-loopback connection. A drill can then ask "did the code even *try* to reach
  169.254.169.254?" without anything leaving the machine.
- Each drill has a time limit, so a defence that hangs is reported as a failure instead of freezing the run.

The drills also run as part of the test suite (`tests/test_diagnostics.py`), so a change that weakens a
defence fails the tests.

### Results: before and after this review

| Drill | Severity | Before | After |
|---|---|---|---|
| Path traversal is blocked | critical | PASS | PASS |
| Symlink escape is blocked | critical | PASS | PASS |
| Zip-slip archive is blocked | critical | PASS | PASS |
| Zip bomb is refused | high | **FAIL**: no size limit | PASS |
| Deleting the workspace root is refused | high | PASS | PASS |
| Reading a huge file stays bounded | high | **FAIL**: 744 MB of RAM for a 300 MB file | PASS: ~0 MB |
| Unsafe workspace locations are refused | critical | **FAIL**: `/` and home accepted | PASS |
| Destructive shell commands are blocked | critical | **FAIL**: missed 17 of 34 variants | PASS: 34/34, no false positives |
| Denied approval means nothing runs | critical | PASS | PASS |
| Timeouts kill the whole process tree | high | **FAIL**: orphan process survived | PASS |
| Output floods stay bounded in memory | high | **FAIL**: 600 MB of RAM for 200 MB of output | PASS: 3 MB |
| Malicious git config can't run code | critical | **FAIL**: fsmonitor + external diff executed | PASS |
| Catastrophic regex can't hang the agent | high | **FAIL**: froze the whole process for 345 s | PASS: killed in 5 s; useful nested patterns still work |
| file:// and other schemes are refused | high | PASS | PASS |
| Cloud metadata is never contacted | critical | **FAIL**: tried to connect | PASS: blocked before connecting |
| Web tools don't reach your private network | high | **FAIL**: tried 10.0.0.1, 192.168.1.1 | PASS |
| Redirects into forbidden addresses are blocked | critical | **FAIL**: followed the redirect | PASS |
| Oversized downloads fail cleanly | medium | **FAIL**: silently truncated | PASS: error, no partial file |
| A corrupted memory file is preserved | high | **FAIL**: overwritten | PASS: moved to `memory.json.corrupt-…` |
| Parallel writes don't lose memories | high | PASS | PASS |
| A crash mid-save leaves old memory intact | high | PASS | PASS |
| Secret environment values are hidden | high | PASS | PASS |
| Secrets are redacted from transcripts | high | **FAIL**: API key written to log | PASS |
| Malformed tool calls can't crash the agent | high | PASS | PASS |
| A model stuck repeating one call is stopped | medium | **FAIL**: 30 identical calls ran | PASS: 3 ran, the rest refused |
| Cut-off tool calls are not executed | high | PASS | PASS |
| Prompt injection can't run commands | critical | PASS | PASS |
| A model crash leaves clean history | medium | PASS | PASS |
| The council survives failures | medium | PASS | PASS |
| **Total** | | **14 / 29, 5 critical failures** | **29 / 29, 0 critical failures** |

## Code health

```bash
python scripts/health_check.py          # full scorecard
python scripts/health_check.py --fast   # skip drills, coverage and the browser test
```

| Check | Tool | Result |
|---|---|---|
| Unit + integration tests | unittest | all pass on Python 3.11, 3.12 and 3.13 |
| Lint + security rules | ruff (config in `pyproject.toml`) | clean |
| Static types | mypy | clean |
| Security scan (medium+) | bandit | clean (each reviewed exception is marked `# Reviewed (Bxxx): reason`) |
| Dead code | vulture | none |
| Minimum Python version | vermin | 3.10 |
| Complexity | radon | nothing rated D or worse |
| Real-browser GUI test | Playwright + Chromium (`scripts/ui_smoke.py`) | no JavaScript errors; works at phone width |
| Safety drills | `diagnose` | 29/29 |

Exceptions that are deliberate (each annotated in code with a reason):
- `except Exception` only at boundaries that must never crash: the tool runner, job threads, doctor, diagnostics.
- `shell=True` only in `run_shell`, which exists to run shell commands, behind approval and the blocklist.
- `tarfile.extractall` only after every member has been validated.
