# Developing

Python 3.10+, standard library only (Claude support optionally uses `pip install anthropic`).

```
python -m hybrid_agent studio                     # the full app, from source (home folder: ~/HybridAgent/home)
python -m hybrid_agent --backend scripted -p x    # smoke test, no model needed
python -m hybrid_agent chat | council | doctor | diagnose | tools
python -m unittest discover -s tests -t .         # all tests, offline
python scripts/health_check.py                    # tests + drills + linters + browser smoke test, as a scorecard
python scripts/ui_smoke.py                        # drive the GUI in Chromium; refreshes docs/screenshots
python scripts/build_exe.py                       # build the app for this computer (pip install pyinstaller)
```

Settings come from environment variables or `.env` (see `.env.example`).

## Layout

| Folder | What lives there |
|---|---|
| `hybrid_agent/core/` | the agent loop, messages, config, home folder |
| `hybrid_agent/backends/` | model connectors: local (Ollama / OpenAI-compatible), Claude, router, scripted |
| `hybrid_agent/tools/` | the tool registry, profiles and 80 built-in tools |
| `hybrid_agent/agents/` | your agents: name, ASCII face, model |
| `hybrid_agent/council/` | several agents deciding together (roundtable, debate, vote, critique) |
| `hybrid_agent/tasks/` | the task queue and scheduler |
| `hybrid_agent/runtime/` | installs and runs the model engine inside the home folder |
| `hybrid_agent/security/` | workspace fence, sandbox, protected paths, backups, audit log, network guard |
| `hybrid_agent/diagnostics/` | the 39 safety drills and integrity checks |
| `hybrid_agent/gui/` | the app's local web server and single-page front end |
| `packaging/` | the PyInstaller recipe and the `HybridAgent.exe` launcher |

Every module's docstring starts with a `[LAYER / name]` label, and a test checks it.

## Building the Windows app

GitHub Actions (`.github/workflows/build.yml`) runs the tests on Windows and Linux for every push, then
builds `HybridAgent.exe` on Windows and smoke-tests it. Publishing a GitHub Release with a `v1.2.3` tag
attaches `HybridAgent-1.2.3-windows-x64.zip` and `SHA256SUMS` to it.

To build the Windows app from Linux, install Wine and a Windows Python with PyInstaller, then
`python scripts/build_exe.py --wine C:/path/to/python.exe`.

## Adding a tool

```python
from pathlib import Path
from hybrid_agent.tools import S, ToolContext, build_registry

tools = build_registry(ToolContext(workspace=Path("workspace")), "minimal")

@tools.tool("shout", "Upper-case some text.", S(text="string"), category="text")
def shout(ctx, text):
    return text.upper()
```

See `examples/custom_tool.py`. A tool that changes things declares `risk="write"` (or `"execute"`) and
`requires_approval=True`, so approvals and safe mode apply to it automatically.
