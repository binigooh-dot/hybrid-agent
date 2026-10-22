"""[GUI] The app: a local web interface with five tabs - Chat, Council, Tasks, Agents, Settings.

    HybridAgent.exe  (or: python -m hybrid_agent studio)   ->  http://127.0.0.1:8765/?token=...

server.py   HTTP server (127.0.0.1 only, per-launch token, strict headers)
jobs.py     event bus (Server-Sent Events), approval broker, background jobs
static/     the single-page app (index.html, app.css, app.js) - no external files
"""
