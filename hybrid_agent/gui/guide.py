"""[GUI / guide] Builds the Agent Builder Knowledge Suite: one self-contained, browsable HTML file.

    python scripts/gen_knowledge_suite.py      -> docs/agent_builder_suite.html (open in any browser)
    python -m hybrid_agent gui                 -> also served live at /guide

Everything shown (tools, profiles, roles, protocols, personas, faces, drills)
is read from the code at build time, so the guide can't drift from reality.
No external files, fonts or scripts: it works offline, from disk.
"""
from __future__ import annotations

import html
import json
import time
from pathlib import Path

from .. import __version__

# Every setting in .env.example (a test checks this list stays complete).
ENV_VARS = [
    ("AGENT_BACKEND", "auto", "auto | claude | local | scripted. 'auto' uses Claude only when a key is set."),
    ("LOCAL_PROVIDER", "ollama", "ollama, or openai for llama.cpp / LM Studio / vLLM."),
    ("LOCAL_BASE_URL", "http://localhost:11434", "Where the local model server listens."),
    ("LOCAL_MODEL", "qwen2.5:7b", "Which local model to use."),
    ("LOCAL_TOOL_MODE", "auto", "native | prompt | auto (switches to prompt mode if tools are unsupported)."),
    ("LOCAL_TIMEOUT", "300", "Seconds to wait for the local model (first call loads it into memory)."),
    ("LOCAL_NUM_CTX", "8192", "Context window for Ollama models."),
    ("AGENT_WORKSPACE", "workspace", "The sandbox folder; file tools can't leave it. / and home are refused."),
    ("AGENT_MAX_STEPS", "25", "Tool-use steps per request before the agent stops."),
    ("AGENT_AUTO_APPROVE", "0", "1 = run risky tools without asking (not recommended)."),
    ("AGENT_MAX_TOOL_OUTPUT", "20000", "Characters of each tool result shown to the model."),
    ("AGENT_SHELL_TIMEOUT", "60", "Seconds before a shell/python command (and its children) is killed."),
    ("AGENT_LOG_DIR", "logs", "Where session logs and council transcripts go (secrets are redacted)."),
    ("AGENT_TOOL_PROFILE", "auto", "Which tools the agent gets; see the Profile Builder."),
    ("AGENT_ALLOW_PRIVATE_NETWORK", "0", "1 = let web tools reach your LAN / this computer."),
    ("AGENT_PERSONA_DIR", "personas", "Folder for your persona JSON files."),
    ("SEARXNG_URL", "(unset)", "Optional self-hosted search engine (no key)."),
    ("COUNCIL_CONFIG", "(unset)", "Default council config file."),
    ("COUNCIL_WORKERS", "1", "Council members answering in parallel."),
    ("ANTHROPIC_API_KEY", "(unset)", "Optional. Enables Claude as the main model."),
    ("CLAUDE_MODEL", "claude-opus-5-5", "Claude model id."),
    ("CLAUDE_EFFORT", "medium", "low | medium | high | xhigh | max."),
    ("CLAUDE_MAX_TOKENS", "16000", "Max output tokens per Claude reply."),
    ("CLAUDE_FALLBACKS", "1", "Server-side refusal fallback."),
]

CATEGORY_INFO = {
    "files": "Read, write, edit, search and organise files in the workspace.",
    "shell": "Run commands and Python (approval required).",
    "code": "Understand code, check syntax, run tests, use git safely.",
    "data": "CSV, JSON, SQLite and XML.",
    "text": "Statistics, regex, extraction, encoding, hashing, ids.",
    "math": "Exact arithmetic, statistics, unit and base conversion.",
    "time": "Dates, durations and time zones.",
    "web": "Read the public web; search without a key.",
    "network": "HTTP requests and checks for your own services.",
    "knowledge": "Wikipedia, arXiv, weather, dictionary, RSS - all keyless.",
    "system": "Information about this computer (read-only).",
    "archives": "zip / tar with zip-slip and zip-bomb protection.",
    "memory": "Long-term notes that survive restarts.",
    "documents": "Search your files by relevance (BM25), no embeddings needed.",
    "agent": "Planning, thinking out loud, asking you, delegating.",
    "council": "The shared whiteboard for council members.",
}

PROTOCOL_INFO = {
    "roundtable": {"steps": ["Everyone answers independently", "Chair synthesises"],
                   "best": "brainstorming, broad coverage, cheapest", "calls": "N + 1"},
    "debate": {"steps": ["Opening statements", "Rebuttal rounds (each sees the others)", "Early stop on consensus",
                         "Chair synthesises"], "best": "hard questions with a defensible answer", "calls": "up to N x R + 1"},
    "vote": {"steps": ["Chair proposes options (if none given)", "Members vote with reasons + confidence",
                       "Weighted tally", "Chair breaks ties and writes it up"], "best": "choosing between options",
             "calls": "N + 1 (+1)"},
    "critique": {"steps": ["Author drafts", "Others critique", "Author revises", "Repeat R times"],
                 "best": "producing a plan, essay or code", "calls": "1 + R x (N - 1) + R"},
}

MODELS = [
    ("qwen2.5:3b", "~2 GB", "4 GB", "minimal", "Low-end laptops; simple tasks"),
    ("llama3.2:3b", "~2 GB", "4 GB", "minimal", "Similar tier"),
    ("qwen2.5:7b", "~4.7 GB", "8 GB", "core", "Default: good balance"),
    ("llama3.1:8b", "~4.9 GB", "8 GB", "core", "Solid general model; good council contrast to qwen"),
    ("mistral-nemo:12b", "~7 GB", "12 GB", "core / coding", "Strong reasoning for its size"),
    ("qwen2.5:14b", "~9 GB", "16 GB", "coding / research", "Much better at multi-step work"),
    ("qwen2.5:32b", "~20 GB", "24-32 GB / GPU", "full", "Approaches hosted-model quality on many tasks"),
]

GLOSSARY = [
    ("Agent", "a chef following a recipe", "A model in a loop: it decides on a step, uses a tool, reads the result, and repeats until done."),
    ("Tool", "a kitchen appliance", "A Python function the model can ask to run, described by a name, a description and a JSON schema."),
    ("Tool profile", "a plumber's toolbox vs the whole hardware store", "The subset of tools an agent is given, so small models aren't overwhelmed."),
    ("Context window", "the size of the model's desk", "How much text the model can see at once. Tool descriptions, history and results all compete for it."),
    ("Backend", "the engine under the bonnet", "The model connection: a local server (Ollama...) or Claude."),
    ("Router / fallback", "Wi-Fi that switches to mobile data", "Try Claude first; if it fails, carry on with the local model."),
    ("Prompt-mode tool calling", "passing notes in a fixed format", "For models without native tool support: the model writes a JSON block and we read it."),
    ("Council", "a board meeting", "Several agents with different roles and models deliberate; a chair writes the decision."),
    ("Protocol", "the rules of order", "How a council meeting runs: roundtable, debate, vote or critique."),
    ("Blackboard", "the whiteboard in the meeting room", "A shared board council members post findings to."),
    ("Persona", "a character in a play", "A council member's name, role, personality, speaking style and face."),
    ("Workspace", "a fenced sandbox", "The only folder file tools may touch."),
    ("Approval", "the bouncer asking for ID", "Risky tools wait for your Allow/Deny before running."),
    ("Prompt injection", "a forged note slipped into the recipe", "Text in a web page or file that tries to give the agent instructions."),
    ("Safety drill", "a fire drill with a smoke machine", "A simulated attack or failure that checks a defence still holds - harmlessly."),
    ("BM25", "the index at the back of a textbook", "A classic relevance-ranking formula used for local document search."),
    ("ReDoS", "a maze with no exit", "A regex that takes exponential time; risky patterns run in a killable process."),
    ("Token", "a word-piece", "The unit models read and write; roughly 4 characters of English."),
]


def _svg_layers() -> str:
    rows = [("CLI / GUI", "you", "#8792e8"), ("COUNCIL", "many agents", "#b07be0"), ("CORE agent loop", "one agent", "#5b6ee1"),
            ("BACKENDS  |  TOOLS", "brain  |  hands", "#2fa37a"), ("CORE basics: messages, config, safety", "shared rules", "#7a869c")]
    parts = ['<svg viewBox="0 0 560 300" role="img" aria-label="Layered architecture" class="diagram">']
    for i, (name, note, col) in enumerate(rows):
        y = 10 + i * 58
        parts.append(f'<rect x="10" y="{y}" width="400" height="48" rx="10" fill="{col}" opacity=".9"/>'
                     f'<text x="26" y="{y + 30}" fill="#fff" font-size="16" font-weight="600">{html.escape(name)}</text>'
                     f'<text x="426" y="{y + 30}" font-size="14" fill="currentColor">{html.escape(note)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _svg_loop() -> str:
    return ('<svg viewBox="0 0 560 220" role="img" aria-label="Agent loop" class="diagram">'
            '<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            '<path d="M0 0L10 5L0 10z" fill="currentColor"/></marker></defs>'
            '<rect x="10" y="80" width="120" height="56" rx="12" fill="#5b6ee1"/><text x="70" y="113" fill="#fff" text-anchor="middle" font-size="15">your request</text>'
            '<rect x="210" y="20" width="140" height="56" rx="12" fill="#2fa37a"/><text x="280" y="53" fill="#fff" text-anchor="middle" font-size="15">model thinks</text>'
            '<rect x="210" y="146" width="140" height="56" rx="12" fill="#d6a12f"/><text x="280" y="179" fill="#fff" text-anchor="middle" font-size="15">tool runs</text>'
            '<rect x="430" y="80" width="120" height="56" rx="12" fill="#b07be0"/><text x="490" y="113" fill="#fff" text-anchor="middle" font-size="15">final answer</text>'
            '<path d="M130 100 L205 55" stroke="currentColor" stroke-width="2" fill="none" marker-end="url(#ar)"/>'
            '<path d="M265 78 L265 142" stroke="currentColor" stroke-width="2" fill="none" marker-end="url(#ar)"/>'
            '<path d="M298 144 L298 80" stroke="currentColor" stroke-width="2" fill="none" marker-end="url(#ar)"/>'
            '<path d="M352 50 L426 100" stroke="currentColor" stroke-width="2" fill="none" marker-end="url(#ar)"/>'
            '<text x="160" y="118" font-size="12" fill="currentColor">tool call</text>'
            '<text x="306" y="118" font-size="12" fill="currentColor">result</text>'
            '<text x="370" y="62" font-size="12" fill="currentColor">no more tools</text></svg>')


def collect_data(cfg=None) -> dict:
    """Everything the guide shows, read from the live code."""
    from ..council.roles import ROLES
    from ..diagnostics.drills import DRILLS
    from ..personas import EXPRESSIONS, load_personas, render_all
    from ..tools import PROFILES, ToolContext, build_full_registry, build_registry
    ctx = ToolContext(workspace=Path("."))
    reg = build_full_registry(ctx)
    tools = []
    for n in reg.names():
        t = reg[n]
        props, req = t.parameters.get("properties", {}), set(t.parameters.get("required", []))
        tools.append({"name": n, "category": t.category, "risk": t.risk, "approval": t.requires_approval,
                      "description": t.description,
                      "params": [{"name": k, "type": v.get("type", "any"), "required": k in req,
                                  "desc": v.get("description", ""), "enum": v.get("enum")} for k, v in props.items()]})
    profiles = {}
    for name in PROFILES:
        r = build_registry(ctx, name)
        profiles[name] = {"tools": r.names(), "tokens": round(len(json.dumps(r.specs())) / 4)}
    persona_dir = getattr(cfg, "persona_dir", None)
    personas = [{"id": p.id, "name": p.name, "title": p.title, "role": p.role, "personality": p.personality,
                 "speaking_style": p.speaking_style, "greeting": p.greeting, "builtin": p.builtin,
                 "faces": render_all(p.face, 150, p.name)} for p in load_personas(persona_dir).values()]
    report = None
    log_dir = getattr(cfg, "log_dir", None)
    if log_dir and (Path(log_dir) / "diagnostics-latest.json").exists():
        try:
            report = json.loads((Path(log_dir) / "diagnostics-latest.json").read_text())
        except (OSError, json.JSONDecodeError):
            report = None
    return {
        "version": __version__, "generated": time.strftime("%Y-%m-%d %H:%M"),
        "tools": tools, "categories": CATEGORY_INFO, "profiles": profiles,
        "tool_tokens": {t["name"]: round(len(json.dumps(reg[str(t["name"])].spec())) / 4) for t in tools},
        "roles": [{"key": r.key, "title": r.title, "persona": r.persona, "tools": r.tools} for r in ROLES.values()],
        "protocols": PROTOCOL_INFO, "personas": personas, "expressions": list(EXPRESSIONS),
        "drills": [{"key": d.key, "title": d.title, "category": d.category, "severity": d.severity,
                    "scenario": d.scenario} for d in DRILLS],
        "report": report, "env": ENV_VARS, "models": MODELS, "glossary": GLOSSARY,
    }


def build_guide_html(nonce: str | None = None, cfg=None) -> str:
    data = collect_data(cfg)
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    n = f' nonce="{html.escape(nonce)}"' if nonce else ""
    return (TEMPLATE.replace("%%NONCE%%", n).replace("%%DATA%%", blob)
            .replace("%%LAYERS%%", _svg_layers()).replace("%%LOOP%%", _svg_loop())
            .replace("%%VERSION%%", html.escape(data["version"])).replace("%%GENERATED%%", data["generated"]))


TEMPLATE = r"""<!doctype html>
<!-- [GUIDE] Agent Builder Knowledge Suite - generated by hybrid_agent/gui/guide.py. Do not edit by hand. -->
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent Builder Suite</title>
<style>
:root{--bg:#f6f7fb;--panel:#fff;--panel2:#f0f2f8;--ink:#1d2233;--muted:#667089;--line:#dfe3ee;--accent:#5b6ee1;--ai:#fff;
--good:#1f9d6b;--bad:#d64545;--warn:#c98a12;--r:14px;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#12141c;--panel:#1a1d28;--panel2:#222636;--ink:#e7e9f2;--muted:#9aa2bb;--line:#2e3346;--accent:#7d8cff;--ai:#0d1020;color-scheme:dark}}
:root[data-theme=dark]{--bg:#12141c;--panel:#1a1d28;--panel2:#222636;--ink:#e7e9f2;--muted:#9aa2bb;--line:#2e3346;--accent:#7d8cff;--ai:#0d1020;color-scheme:dark}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--ink);font:15.5px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}code,.mono{font-family:var(--mono);font-size:.88em}
.layout{display:grid;grid-template-columns:240px minmax(0,1fr);min-height:100vh}
nav.side{position:sticky;top:0;height:100vh;overflow:auto;padding:18px 14px;border-right:1px solid var(--line);background:var(--panel)}
nav.side .logo{font-weight:800;font-size:17px;margin-bottom:2px}nav.side .ver{color:var(--muted);font-size:12px;margin-bottom:14px}
nav.side a{display:block;padding:6px 10px;border-radius:8px;color:var(--muted);text-decoration:none;font-size:14.5px}
nav.side a.on{background:var(--panel2);color:var(--ink);font-weight:600}
main{padding:24px 28px 80px;max-width:1150px;min-width:0}
section{margin-bottom:44px;scroll-margin-top:16px}h1{font-size:30px;margin:0 0 6px}h2{font-size:22px;margin:0 0 6px}h3{font-size:16px;margin:16px 0 6px}
.lead{color:var(--muted);font-size:16.5px;margin-top:0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:16px;min-width:0}
.grid{display:grid;gap:12px}.g3{grid-template-columns:repeat(auto-fit,minmax(230px,1fr))}.g2{grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
.analogy{border-left:4px solid var(--accent);background:var(--panel2);padding:10px 14px;border-radius:0 10px 10px 0;margin:12px 0}
.diagram{width:100%;max-width:560px;height:auto;color:var(--ink)}
pre.cmd{position:relative;background:#141824;color:#e6e9f5;padding:12px 14px;border-radius:10px;overflow:auto;font-size:13.5px;margin:6px 0}
pre.cmd button{position:absolute;top:6px;right:6px;font-size:12px;border:0;border-radius:6px;padding:3px 8px;cursor:pointer;background:#2b3248;color:#fff}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}.tabs button,.chip{border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:4px 12px;cursor:pointer;font:inherit;font-size:13.5px;color:inherit}
.tabs button[aria-selected=true],.chip[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:var(--ai)}
input[type=text],select,textarea{font:inherit;color:inherit;padding:8px 10px;border-radius:9px;border:1px solid var(--line);background:var(--panel)}
.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}
.tag{display:inline-block;font-size:11.5px;padding:1px 8px;border-radius:999px;background:var(--panel2);color:var(--muted);margin-right:4px}
.tag.read{color:var(--good)}.tag.network{color:var(--accent)}.tag.write{color:var(--warn)}.tag.execute{color:var(--bad)}
.tool h4{margin:0;font-family:var(--mono);font-size:14.5px;overflow-wrap:anywhere}.tool p{margin:6px 0;font-size:14px}
.tool details{font-size:13px}.tool table{font-size:12.5px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
.tw{overflow-x:auto}
.gauge{height:14px;background:var(--panel2);border-radius:8px;overflow:hidden}.gauge div{height:100%;background:var(--accent);transition:width .2s}
.gauge.over div{background:var(--bad)}
.cat-block{margin:10px 0}.cat-block h4{margin:8px 0 4px;font-size:14px}
.cbs{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:13px;font-family:var(--mono)}.cbs label{display:flex;gap:4px;align-items:center}
.faces{display:flex;flex-wrap:wrap;gap:6px}.faces figure{margin:0;text-align:center;font-size:12px;color:var(--muted)}
.faces svg{width:96px;height:96px}.persona{display:grid;grid-template-columns:150px minmax(0,1fr);gap:14px;align-items:start}
.persona .big svg{width:150px;height:150px}
@media (max-width:820px){.layout{grid-template-columns:minmax(0,1fr)}nav.side{position:static;height:auto;display:flex;flex-wrap:wrap;gap:4px;border-right:0;border-bottom:1px solid var(--line)}
nav.side .logo,nav.side .ver{width:100%}main{padding:16px}.persona{grid-template-columns:minmax(0,1fr)}}
.steps{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.steps span{background:var(--panel2);border-radius:8px;padding:4px 10px;font-size:13.5px}
.steps i{color:var(--muted);font-style:normal}
.ladder{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.ladder div{border-radius:10px;padding:10px;color:#fff;font-size:13.5px}
.pass{color:var(--good);font-weight:700}.fail{color:var(--bad);font-weight:700}
.toolbar{position:fixed;right:14px;bottom:14px}.toolbar button{border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:8px 12px;cursor:pointer;color:inherit}
</style></head>
<body>
<div class="layout">
<nav class="side" id="nav">
  <div class="logo">Agent Builder Suite</div><div class="ver">v%%VERSION%% · built %%GENERATED%%</div>
  <a href="#welcome">Welcome</a><a href="#start">Quick start</a><a href="#how">How agents work</a>
  <a href="#tools">Tool explorer</a><a href="#profiles">Profile builder</a><a href="#council">Council designer</a>
  <a href="#protocols">Protocols &amp; roles</a><a href="#personas">Personas &amp; faces</a><a href="#safety">Safety centre</a>
  <a href="#setup">Setup &amp; models</a><a href="#glossary">Glossary</a>
</nav>
<main>
<section id="welcome">
  <h1>Build agents that run on your own computer</h1>
  <p class="lead">A local-first agent toolkit: a tool-using agent that needs <b>no API key</b> (a local model does the thinking),
  optional <b>Claude</b> as a stronger brain, and a <b>council</b> of persona agents with faces that deliberate together.</p>
  <div class="grid g3" id="stats"></div>
  <h3>The layers</h3>
  <div class="grid g2"><div class="card">%%LAYERS%%</div>
  <div class="card"><div class="analogy"><b>Analogy:</b> a building. Each floor only uses the floors below it. You talk to the top floor
  (command line or GUI); the council floor runs meetings; the core floor is one agent's think-act loop; underneath, the
  <i>brain</i> (model backends) and the <i>hands</i> (tools) share one set of rules (messages, config, safety).</div>
  <p>Every Python file starts with a <code>[LAYER / name]</code> label, and <code>docs/FILE_MAP.md</code> lists them all.</p></div></div>
</section>

<section id="start">
  <h2>Quick start</h2>
  <div class="tabs" id="start-tabs"></div><div id="start-body"></div>
</section>

<section id="how">
  <h2>How an agent works</h2>
  <div class="grid g2"><div class="card">%%LOOP%%</div>
  <div class="card"><div class="analogy"><b>Analogy:</b> a chef with a recipe. Each step they either ask a kitchen hand (a tool) to fetch,
  chop or measure something, or plate the dish (the final answer). A step limit stops a chef who keeps asking forever.</div>
  <ul><li><b>Backend</b>: the model. Local (Ollama, llama.cpp, LM Studio) or Claude, with automatic fallback.</li>
  <li><b>Tools</b>: Python functions with a name, description and JSON schema. Arguments are validated before they run.</li>
  <li><b>Safety</b>: a workspace fence, approval prompts, a blocklist, a network guard, redacted logs.</li>
  <li><b>Guards in the loop</b>: never runs cut-off tool calls, stops repeated identical calls, rolls back on failure, and can be stopped.</li></ul></div></div>
</section>

<section id="tools">
  <h2>Tool explorer</h2>
  <p class="lead" id="tools-lead"></p>
  <div class="filters"><input type="text" id="tq" placeholder="Search name or description…" aria-label="Search tools">
  <select id="trisk" aria-label="Risk"><option value="">any risk</option><option>read</option><option>network</option><option>write</option><option>execute</option></select>
  <select id="tprof" aria-label="Profile"><option value="">any profile</option></select><span id="tcount" class="mono"></span></div>
  <div id="tcats" class="tabs"></div>
  <div class="card" style="margin:10px 0"><b>Risk ladder</b><div class="ladder" style="margin-top:8px">
  <div style="background:#1f9d6b">read<br><small>only looks</small></div><div style="background:#5b6ee1">network<br><small>contacts other machines</small></div>
  <div style="background:#c98a12">write<br><small>changes files</small></div><div style="background:#d64545">execute<br><small>runs code</small></div></div></div>
  <div id="tgrid" class="grid g3"></div>
</section>

<section id="profiles">
  <h2>Profile builder</h2>
  <p class="lead">Every tool's description is sent to the model on every request. Pick only what an agent needs, so its context
  window stays free for the actual work.</p>
  <div class="analogy"><b>Analogy:</b> send a plumber with a plumber's toolbox, not the whole hardware store.</div>
  <div class="grid g2"><div class="card">
    <div class="filters"><label>Start from <select id="pbase"></select></label>
    <label>Model context <select id="pctx"><option value="4096">4k</option><option value="8192" selected>8k</option><option value="16384">16k</option><option value="32768">32k</option><option value="200000">Claude (large)</option></select></label></div>
    <div id="pcats"></div></div>
  <div class="card" style="position:sticky;top:16px;align-self:start"><h3 style="margin-top:0">Result</h3><div id="psum"></div><div class="gauge" id="pgauge"><div></div></div>
    <p class="muted" style="font-size:13px">Tool descriptions as a share of the context window. Aim for under ~25% on local models.</p>
    <h3>Profile string</h3><pre class="cmd" id="pstr"></pre>
    <p style="font-size:13.5px">Use it with <code>--tools "…"</code>, <code>AGENT_TOOL_PROFILE</code>, or a council member's <code>"tools"</code> field.</p></div></div>
</section>

<section id="council">
  <h2>Council designer</h2>
  <p class="lead">Choose members, a chair and a protocol. You get a config file and the command to run it.</p>
  <div class="grid g2"><div class="card">
    <h3 style="margin-top:0">Members</h3><div id="cmembers" class="faces"></div>
    <h3>Add a role-based member</h3><div class="filters"><select id="crole"></select><button class="chip" id="cadd">+ add</button></div>
    <div class="filters"><label>Chair <select id="cchair"></select></label><label>Protocol <select id="cproto"></select></label>
    <label>Rounds <select id="crounds"><option>1</option><option selected>2</option><option>3</option></select></label></div>
    <input type="text" id="coptions" placeholder="Vote options, comma separated (optional)" style="width:100%">
  </div><div class="card"><div id="cest"></div><h3>Config (save as council.json)</h3><pre class="cmd" id="cjson"></pre>
    <button class="chip" id="cdl">Download council.json</button><h3>Run it</h3><pre class="cmd" id="ccmd"></pre></div></div>
</section>

<section id="protocols"><h2>Protocols &amp; roles</h2>
  <div class="analogy"><b>Analogy:</b> a protocol is the meeting's rules of order: a brainstorm, a debate, a motion and vote, or a draft-and-review.</div>
  <div class="grid g2" id="protos"></div><h3>Roles</h3><div class="tw"><table id="roles"></table></div></section>

<section id="personas"><h2>Personas &amp; faces</h2>
  <p class="lead">A persona is a council member with a name, role, personality, speaking style, and a procedurally drawn face
  with seven expressions. The GUI switches expressions live: thinking while they work, speaking when they answer,
  happy or concerned when the vote is in.</p>
  <div id="pgallery" class="grid"></div>
  <h3>Make your own</h3>
  <p>Use the GUI's Personas tab (live face editor), or drop a JSON file in <code>./personas/</code>:</p>
  <pre class="cmd" id="pjson"></pre>
  <p style="font-size:14px">Set <code>"image"</code> to a picture file in the persona folder (or an https URL) to use a portrait instead of the drawn face.
  That's the groundwork for generated portraits or animated avatars later.</p></section>

<section id="safety"><h2>Safety centre</h2>
  <p class="lead">Defence in depth. Each layer catches what the one before misses, and fire drills prove they hold.</p>
  <div class="grid g3" id="layers"></div>
  <h3>Fire drills</h3><p>Run them with <code>python -m hybrid_agent diagnose</code> or the GUI's Safety tab. Each one simulates an attack or failure
  in a throwaway folder. Destructive commands are only ever <i>checked</i>, never executed, and tripwires block real network
  connections during drills.</p>
  <div id="report"></div><div class="tw"><table id="drills"></table></div></section>

<section id="setup"><h2>Setup &amp; models</h2>
  <h3>Choosing a local model</h3><div class="tw"><table id="models"></table></div>
  <p style="font-size:14px">Rule of thumb: about 0.6 GB of memory per billion parameters at 4-bit, plus room for context. For a council,
  different models (qwen + llama + mistral) disagree more usefully than three copies of one.</p>
  <h3>Settings (.env)</h3><div class="tw"><table id="env"></table></div></section>

<section id="glossary"><h2>Glossary</h2><div class="grid g2" id="gloss"></div></section>
</main></div>
<div class="toolbar"><button id="theme" title="Toggle light/dark">◐ theme</button></div>
<script type="application/json" id="data">%%DATA%%</script>
<script%%NONCE%%>
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const $ = (s) => document.querySelector(s);
function el(t, a = {}, ...k) { const e = document.createElement(t);
  for (const [x, v] of Object.entries(a)) { if (x === "text") e.textContent = v; else if (x === "html") e.innerHTML = v;
    else if (x.startsWith("on")) e.addEventListener(x.slice(2), v); else if (v != null && v !== false) e.setAttribute(x, v); }
  for (const c of k) if (c != null) e.append(c); return e; }
function cmd(text) { const pre = el("pre", { class: "cmd" }, text);
  const b = el("button", { text: "copy", onclick: () => { (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject())
    .then(() => { b.textContent = "copied"; setTimeout(() => b.textContent = "copy", 1200); })
    .catch(() => { const r = document.createRange(); r.selectNodeContents(pre); getSelection().removeAllRanges(); getSelection().addRange(r); }); } });
  pre.append(b); return pre; }
function row(cells, th) { return el("tr", {}, ...cells.map((c) => el(th ? "th" : "td", typeof c === "string" ? { text: c } : {}, typeof c === "string" ? null : c))); }

// theme
$("#theme").onclick = () => { const r = document.documentElement;
  const dark = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  r.dataset.theme = dark ? "light" : "dark"; };

// stats
const cats = [...new Set(D.tools.map((t) => t.category))];
for (const [n, l] of [[D.tools.length, "tools"], [cats.length, "categories"], [Object.keys(D.profiles).length, "profiles"],
  [D.roles.length, "council roles"], [Object.keys(D.protocols).length, "protocols"], [D.drills.length, "safety drills"]])
  $("#stats").append(el("div", { class: "card" }, el("div", { text: String(n), style: "font-size:28px;font-weight:800" }), el("div", { class: "lead", text: l })));

// quick start
const START = {
  "No API key": ["# 1. install Ollama from https://ollama.com/download, then:", "ollama serve &", "ollama pull qwen2.5:7b",
    "python3 -m hybrid_agent doctor", "python3 -m hybrid_agent --backend local"],
  "Try without a model": ["python3 -m hybrid_agent --backend scripted -y -p demo",
    "python3 -m hybrid_agent council --backend scripted --personas sage,vex,nova -p \"test\""],
  "Council": ["python3 -m hybrid_agent council --personas sage,vex,nova -p \"Rust or Go first?\" --protocol vote --options \"Rust,Go\""],
  "GUI": ["python3 -m hybrid_agent gui", "# opens http://127.0.0.1:8765/?token=...  (only this computer can connect)"],
  "Add Claude": ["pip install anthropic", "export ANTHROPIC_API_KEY=sk-ant-...", "python3 -m hybrid_agent"],
  "Safety check": ["python3 -m hybrid_agent diagnose"],
};
function showStart(k) { [...$("#start-tabs").children].forEach((b) => b.setAttribute("aria-selected", String(b.textContent === k)));
  $("#start-body").replaceChildren(cmd(START[k].join("\n"))); }
for (const k of Object.keys(START)) $("#start-tabs").append(el("button", { text: k, onclick: () => showStart(k) }));
showStart("No API key");

// tool explorer
$("#tools-lead").textContent = `${D.tools.length} tools in ${cats.length} categories, all running on Python's standard library. None needs an API key.`;
let tcat = "";
for (const p of Object.keys(D.profiles)) $("#tprof").append(el("option", { value: p, text: `${p} (${D.profiles[p].tools.length})` }));
function renderCats() { $("#tcats").replaceChildren(...["", ...cats.sort()].map((c) => el("button", { class: "chip", "aria-pressed": String(c === tcat),
  text: c || "all", title: D.categories[c] || "", onclick: () => { tcat = c; renderCats(); renderTools(); } }))); }
function renderTools() {
  const q = $("#tq").value.toLowerCase(), risk = $("#trisk").value, prof = $("#tprof").value; let n = 0;
  const g = $("#tgrid"); g.replaceChildren();
  for (const t of D.tools) {
    if ((tcat && t.category !== tcat) || (risk && t.risk !== risk) || (prof && !D.profiles[prof].tools.includes(t.name))) continue;
    if (q && !(t.name + " " + t.description).toLowerCase().includes(q)) continue;
    n++;
    const example = {}; for (const p of t.params) if (p.required) example[p.name] = p.enum ? p.enum[0] : p.type === "string" ? "…" : p.type === "integer" ? 1 : p.type === "boolean" ? true : p.type === "array" ? [] : {};
    const tbl = el("table", {}, row(["arg", "type", "about"], true), ...t.params.map((p) => row([p.name + (p.required ? "" : "?"), p.enum ? p.enum.join(" | ") : p.type, p.desc || ""])));
    g.append(el("div", { class: "card tool" }, el("h4", { text: t.name }),
      el("span", { class: `tag ${t.risk}`, text: t.risk }), el("span", { class: "tag", text: t.category }),
      t.approval ? el("span", { class: "tag", text: "asks approval" }) : null, el("p", { text: t.description }),
      el("details", {}, el("summary", { text: `${t.params.length} argument(s) · ≈${D.tool_tokens[t.name]} tokens` }),
        t.params.length ? tbl : el("p", { text: "No arguments." }), el("div", { class: "mono", text: "example call: " + JSON.stringify({ tool: t.name, arguments: example }) }))));
  }
  $("#tcount").textContent = `${n} shown`;
}
["#tq", "#trisk", "#tprof"].forEach((s) => $(s).addEventListener("input", renderTools)); renderCats(); renderTools();

// profile builder
const chosen = new Set();
for (const p of Object.keys(D.profiles)) $("#pbase").append(el("option", { value: p, text: p }));
$("#pbase").value = "core";
function loadBase() { chosen.clear(); D.profiles[$("#pbase").value].tools.forEach((t) => chosen.add(t)); renderPB(); }
function renderPB() {
  const box = $("#pcats"); box.replaceChildren();
  for (const c of cats) {
    const tools = D.tools.filter((t) => t.category === c);
    box.append(el("div", { class: "cat-block" }, el("h4", { text: `${c} — ${D.categories[c] || ""}` }),
      el("div", { class: "cbs" }, ...tools.map((t) => { const cb = el("input", { type: "checkbox" }); cb.checked = chosen.has(t.name);
        cb.onchange = () => { cb.checked ? chosen.add(t.name) : chosen.delete(t.name); summary(); };
        return el("label", { title: t.description }, cb, t.name); }))));
  }
  summary();
}
function summary() {
  const tok = [...chosen].reduce((a, t) => a + (D.tool_tokens[t] || 0), 0), ctx = +$("#pctx").value, pct = (100 * tok) / ctx;
  $("#psum").textContent = `${chosen.size} tools · ≈${tok.toLocaleString()} tokens of tool descriptions · ${pct.toFixed(1)}% of the context window`;
  $("#pgauge").classList.toggle("over", pct > 25); $("#pgauge div").style.width = Math.min(pct, 100) + "%";
  const base = new Set(D.profiles[$("#pbase").value].tools);
  const add = [...chosen].filter((t) => !base.has(t)).sort().map((t) => "+" + t), rm = [...base].filter((t) => !chosen.has(t)).sort().map((t) => "-" + t);
  $("#pstr").textContent = [$("#pbase").value, ...add, ...rm].join(",");
}
$("#pbase").onchange = loadBase; $("#pctx").onchange = summary; loadBase();

// council designer
const members = [];
const cpick = {};
for (const p of D.personas) cpick[p.id] = ["sage", "vex", "nova"].includes(p.id);
for (const r of D.roles) $("#crole").append(el("option", { value: r.key, text: r.title }));
for (const k of Object.keys(D.protocols)) $("#cproto").append(el("option", { value: k, text: k }));
$("#cproto").value = "debate";
$("#cadd").onclick = () => { const role = $("#crole").value; let i = 1; while (members.some((m) => m.name === `${role}${i}`)) i++; members.push({ name: `${role}${i}`, role }); renderCouncil(); };
function renderCouncil() {
  const box = $("#cmembers"); box.replaceChildren();
  for (const p of D.personas) { const f = el("figure", { style: `cursor:pointer;opacity:${cpick[p.id] ? 1 : .35}`, title: "click to toggle", html: p.faces[cpick[p.id] ? "happy" : "neutral"] });
    f.append(el("figcaption", { text: `${p.name} (${p.role})` })); f.onclick = () => { cpick[p.id] = !cpick[p.id]; renderCouncil(); }; box.append(f); }
  for (const m of members) { const f = el("figure", { style: "cursor:pointer" }, el("div", { text: "👤", style: "font-size:56px;line-height:96px;width:96px" }), el("figcaption", { text: `${m.name} ✕` }));
    f.onclick = () => { members.splice(members.indexOf(m), 1); renderCouncil(); }; box.append(f); }
  const all = [...D.personas.filter((p) => cpick[p.id]).map((p) => ({ name: p.id, role: p.role })), ...members];
  const prev = $("#cchair").value; $("#cchair").replaceChildren(el("option", { value: "", text: "automatic" }), ...all.map((m) => el("option", { value: m.name, text: m.name })));
  if (all.some((m) => m.name === prev)) $("#cchair").value = prev;
  const proto = $("#cproto").value, r = +$("#crounds").value, opts = $("#coptions").value.split(",").map((s) => s.trim()).filter(Boolean);
  const chair = $("#cchair").value || (all.find((m) => m.role === "chair") || all[0] || {}).name;
  const n = Math.max(all.length - (chair ? 1 : 0), 1);
  const calls = { roundtable: n + 1, debate: n * r + 1, vote: n + 2, critique: 1 + r * Math.max(n - 1, 0) + r }[proto];
  $("#cest").replaceChildren(el("div", { class: "steps" }, ...D.protocols[proto].steps.flatMap((s, i) => i ? [el("i", { text: "→" }), el("span", { text: s })] : [el("span", { text: s })])),
    el("p", { text: `${all.length} members · chair: ${chair || "—"} · ≈${calls} model contributions · best for ${D.protocols[proto].best}.` }));
  const cfg = { protocol: proto, rounds: r };
  if ($("#cchair").value) cfg.chair = $("#cchair").value;
  if (opts.length) cfg.options = opts;
  const ps = D.personas.filter((p) => cpick[p.id]).map((p) => p.id); if (ps.length) cfg.personas = ps;
  if (members.length) cfg.members = members;
  const json = JSON.stringify(cfg, null, 2); $("#cjson").textContent = json;
  $("#ccmd").textContent = `python3 -m hybrid_agent council --council-config council.json -p "your question"`;
  $("#cdl").onclick = () => { const a = el("a", { href: URL.createObjectURL(new Blob([json], { type: "application/json" })), download: "council.json" }); document.body.append(a); a.click(); a.remove(); };
}
["#cchair", "#cproto", "#crounds", "#coptions"].forEach((s) => $(s).addEventListener("input", renderCouncil)); renderCouncil();

// protocols + roles
for (const [k, p] of Object.entries(D.protocols)) $("#protos").append(el("div", { class: "card" }, el("h3", { text: k, style: "margin-top:0" }),
  el("div", { class: "steps" }, ...p.steps.flatMap((s, i) => i ? [el("i", { text: "→" }), el("span", { text: s })] : [el("span", { text: s })])),
  el("p", { text: `Best for ${p.best}. Model contributions: ${p.calls} (N members, R rounds).` })));
$("#roles").append(row(["Role", "Persona (what it cares about)", "Default tools"], true), ...D.roles.map((r) => row([r.title, r.persona, r.tools])));

// personas
for (const p of D.personas) {
  const big = el("div", { class: "big", html: p.faces.neutral });
  const strip = el("div", { class: "faces" }, ...D.expressions.map((ex) => { const f = el("figure", { style: "cursor:pointer", html: p.faces[ex] });
    f.append(el("figcaption", { text: ex })); f.onclick = () => big.innerHTML = p.faces[ex]; return f; }));
  $("#pgallery").append(el("div", { class: "card persona" }, big, el("div", {}, el("h3", { text: `${p.name} — ${p.title}`, style: "margin-top:0" }),
    el("p", { text: p.personality }), el("p", { class: "lead", text: `Style: ${p.speaking_style}` }), p.greeting ? el("p", { text: `“${p.greeting}”` }) : null, strip)));
}
$("#pjson").textContent = JSON.stringify({ id: "atlas", name: "Atlas", role: "engineer", title: "The Builder",
  personality: "Pragmatic and hands-on; prototypes before debating.", speaking_style: "short sentences, concrete steps",
  greeting: "Show me the constraints and I'll show you a plan.", backend: "local:llama3.1:8b", weight: 1.0,
  face: { skin: "#b97a4f", hair: "#1f1a17", hair_style: "short", eyes: "#4a3b2c", shape: "square", accent: "#d6a12f", glasses: true } }, null, 2);

// safety
const LAYERS = [["Workspace fence", "Paths can't leave the workspace: .., absolute paths and symlinks are refused. / and home can't be the workspace."],
  ["Approval", "Shell, Python, tests, deletes, moves, downloads and overwrites wait for your Allow. No answer means Deny."],
  ["Command blocklist", "Recursive deletes outside the workspace, disk formatting, fork bombs, curl|sh and more are refused, even if approved."],
  ["Network guard", "Web tools reach the public internet only. Cloud-metadata and link-local addresses are always blocked, including via redirects."],
  ["Resource limits", "Timeouts kill the whole process tree; output, file reads, downloads and archives are size-capped; risky regexes run in a killable process."],
  ["Git hardening", "A repository's own config can't make git run programs (fsmonitor, hooks, external diff, pagers…)."],
  ["Loop guards", "Cut-off tool calls never run, repeated identical calls are refused, and Stop rolls back cleanly."],
  ["Secret redaction", "API keys, tokens and private keys are scrubbed from logs, transcripts and the GUI feed."],
  ["Data integrity", "Atomic writes and file locks; a corrupt memory file is preserved, never wiped."]];
for (const [t, d] of LAYERS) $("#layers").append(el("div", { class: "card" }, el("b", { text: t }), el("p", { text: d, style: "margin:6px 0 0;font-size:14px" })));
const rep = D.report ? Object.fromEntries(D.report.drills.map((d) => [d.key, d])) : null;
if (D.report) $("#report").append(el("p", { html: "" }, el("b", { text: `Last run ${D.report.time}: ${D.report.passed}/${D.report.total} passed` }),
  D.report.critical_failures.length ? el("span", { class: "fail", text: ` — critical: ${D.report.critical_failures.join(", ")}` }) : el("span", { class: "pass", text: " — no critical failures" })));
$("#drills").append(row(["Drill", "Area", "Severity", "Scenario", rep ? "Last result" : ""], true),
  ...D.drills.map((d) => row([d.title, d.category, d.severity, d.scenario, rep && rep[d.key] ? el("span", { class: rep[d.key].passed ? "pass" : "fail", text: rep[d.key].passed ? "PASS" : "FAIL" }) : ""])));

// setup
$("#models").append(row(["Ollama model", "Download", "RAM", "Suggested profile", "Notes"], true), ...D.models.map((m) => row(m)));
$("#env").append(row(["Variable", "Default", "Meaning"], true), ...D.env.map((e) => row([el("code", { text: e[0] }), e[1], e[2]])));

// glossary
for (const [term, analogy, def] of D.glossary) $("#gloss").append(el("div", { class: "card" }, el("b", { text: term }), el("div", { class: "lead", text: `like ${analogy}`, style: "font-size:14px" }), el("div", { text: def, style: "font-size:14.5px" })));

// scrollspy
const links = [...document.querySelectorAll("nav.side a")];
const spy = new IntersectionObserver((es) => { for (const e of es) if (e.isIntersecting) links.forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + e.target.id)); }, { rootMargin: "-20% 0px -70% 0px" });
document.querySelectorAll("main section").forEach((s) => spy.observe(s));
</script>
</body></html>
"""
