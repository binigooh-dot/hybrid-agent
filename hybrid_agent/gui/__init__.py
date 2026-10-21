"""[GUI] Local web interface: chat, council stage with persona faces, persona editor,
tool browser, safety centre, and the Agent Builder knowledge suite.

    python -m hybrid_agent gui         ->  http://127.0.0.1:8765/?token=...

server.py   HTTP server (127.0.0.1 only, per-launch token, strict headers)
jobs.py     event bus (Server-Sent Events), approval broker, background jobs
guide.py    builds the self-contained Agent Builder knowledge suite HTML
static/     the single-page app (index.html, app.css, app.js) - no external files
"""
