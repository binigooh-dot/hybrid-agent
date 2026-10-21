# Hybrid Agent 1.0.0

A tool-using agent and a council of persona agents that run on **your own computer with no API key**
(a local model via Ollama, llama.cpp or LM Studio), with **Claude** as an optional brain. It has a local
web GUI (Agent Studio) and kernel-level safety.

## Install

```bash
pip install hybrid_agent-1.0.0-py3-none-any.whl          # Python 3.10+, no dependencies
pip install "hybrid_agent-1.0.0-py3-none-any.whl[claude]" # optional: Claude support
sudo apt install bubblewrap                               # Linux: enables the strict sandbox (recommended)

hybrid-agent doctor                       # what's ready, what's missing
hybrid-agent gui --backend scripted       # try the GUI with demo replies, no model needed
hybrid-agent gui                          # the real thing (after `ollama pull qwen2.5:7b`)
```

Check the download: `sha256sum -c SHA256SUMS`. After installing, `hybrid-agent diagnose` also verifies
every package file against the built-in integrity manifest.

## Highlights

- **80 tools** in 16 categories, with tool profiles so small models stay focused.
- **Council:** 8 roles; 4 protocols (roundtable, debate, vote, critique); weighted votes; mixed models.
- **Personas with animated ASCII faces:** 7 expressions, plus talking, thinking and blinking animations.
  About 2 KB per persona.
- **Agent Studio GUI:**
  - a 3-step council with a live stage and a decision card;
  - chat;
  - a face builder;
  - a tool browser;
  - a safety centre with one-click undo;
  - clear Allow/Deny approvals.
- **Hard safety:**
  - a kernel sandbox: system read-only, home hidden, only the workspace writable;
  - CPU, memory and file-size caps;
  - protected system, hardware and agent files;
  - automatic backups with undo;
  - a disk guard, safe mode, an audit log and an integrity manifest.
- **Verified:** 39/39 safety drills, 133 tests, and ruff, mypy, bandit, vulture and radon all clean.
  A real-browser GUI test also passes.

## Known limits

- Network access from inside the sandbox is not cut.
- Windows gets environment scrubbing but no filesystem sandbox (use WSL for strict isolation).
- Local models must support tool calling, or use prompt mode (automatic).
