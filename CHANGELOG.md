# Changelog

## 1.2.0: simpler, Windows-first

- **One-click setup.** The app checks your PC's memory, suggests a model that fits, then installs the
  engine and downloads the model with one button and a progress bar.
- **Agents instead of personas.** Three plain ASCII smiley faces (Blue, Green, Orange) with small
  differences, no built-in personalities. Make your own in the Agents tab: name, face, model.
- **Five tabs:** Chat, Council, Tasks, Agents, Settings. Settings combines the model engine, safety status,
  undo history, online check and preferences.
- **Windows app:** opens in its own window (Microsoft Edge app mode, else your browser), a shorter start-up
  message, and a 5-line START HERE.txt. Downloads are Windows-only now; Linux and macOS run from source.
- **Shorter docs:** one-page README, one-page [docs/SAFETY.md](docs/SAFETY.md), [docs/DEVELOPING.md](docs/DEVELOPING.md).
- **Removed:** the tool browser, the knowledge-suite page, the bundled face font, the wheel downloads.
- Tasks and council files from 1.1 still load (`persona` fields map to agents).

## 1.1.1

- Fixes from the first run on real Windows: protected system paths, `/` in tool output, file-map sorting.
- CI actions moved to Node 24.

## 1.1.0

- The desktop app: `HybridAgent.exe` with a portable home folder, model engine manager, task scheduler,
  and live web tools (Wikipedia, search, weather, arXiv) with an honest User-Agent and proxy support.

## 1.0.0

- Hard safety: kernel sandbox, protected paths, backups with undo, audit log, disk guard, safe mode,
  integrity manifest, 39 safety drills. 80 tools, councils, the local web GUI.
