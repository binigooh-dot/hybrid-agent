# Hybrid Agent 1.1.0: the desktop app

A tool-using agent and a council of persona agents that run on **your own computer with no API key**, now as a
**one-folder desktop app**: the GUI, the local model engine, your models, tasks and files live together.

## Download and run

| File | For |
|---|---|
| `HybridAgent-1.1.0-windows-x64.zip` | Windows 10/11 (64-bit): unzip, double-click **HybridAgent.exe** |
| `HybridAgent-1.1.0-linux-x86_64.zip` | Linux x86-64: unzip, run `./HybridAgent` (install `bubblewrap` for the strict sandbox) |
| `hybrid_agent-1.1.0-py3-none-any.whl` / `.tar.gz` | Python 3.10+ anywhere: `pip install …whl`, then `hybrid-agent studio` |

Then open the **Control** tab: *Install engine* → *Download* a model → *Run check* (confirms the agents can
reach Wikipedia and the web). Check downloads with `sha256sum -c SHA256SUMS`.

Windows may show a SmartScreen warning because the app isn't code-signed ("More info" → "Run anyway").

## New in 1.1.0

- **Desktop app**: a portable `home/` folder holds settings, workspace, personas, logs, tasks, the model
  engine and models. It reopens the existing window instead of starting twice, and Quit stops everything.
- **Control panel**: install/start/stop Ollama inside the folder; download, switch and delete models with
  progress; online check; settings; storage.
- **Tasks**: queue and schedule agents, councils or safety drills (once, every N minutes, daily, weekdays).
  One at a time, with run history and saved results. Unattended tasks are read-only by default.
- **Online, politely**: honest User-Agent with your contact, Retry-After, proxy support, and a search chain
  (SearXNG → DuckDuckGo → Marginalia → Wikipedia) that never pretends to be a browser.
- **Crisper faces**: box-drawing faces in a bundled font that joins up on every computer; talking, thinking
  and blinking animations.
- **GUI**: one health signal in the top bar, grouped tabs, new Tasks and Control tabs.
- **Windows fixes** found by testing the .exe: UTF-8 everywhere, bundled time zones, whole-tree timeouts.

## Verified

- 158 tests and 39/39 safety drills, from source, in the packaged Linux app, and in the Windows .exe
  (under Wine). ruff, mypy, bandit, vulture and radon are clean, and a real-browser GUI test passes.
- Live end to end: the engine downloaded into the folder, a model was pulled, and scheduled tasks ran on the
  local model using live Wikipedia and weather data.
- The included GitHub workflow re-runs everything on real Windows, macOS and Linux.

## Known limits

- Windows has no OS sandbox the app can turn on by itself: commands run with secrets removed and need your
  approval. Use WSL plus the Linux build for full isolation.
- Network access from inside the Linux sandbox isn't cut.
- Search engines may refuse automated requests from some networks; your own SearXNG is the most reliable option.
