# 06 · GUI (Agent Studio) and personas with faces

## Start it

```bash
python -m hybrid_agent gui                 # opens http://127.0.0.1:8765/?token=...
python -m hybrid_agent gui --port 9000 --no-browser
python -m hybrid_agent gui --backend scripted   # try it with canned replies, no model needed
```

Only this computer can connect, and the link contains a secret token that changes on every launch.
Keep the terminal open; press Ctrl+C to stop.

## What's in it

| Tab | What you can do |
|---|---|
| **Council** | Pick members by their faces, choose the chair and protocol, ask a question. Each face reacts live: *thinking* while they work, *speaking* when they answer, then *happy* or *concerned* depending on whether the vote went their way. You get vote bars, the chair's answer and a timeline. |
| **Chat** | Talk to one agent, optionally as a persona (their face and greeting), and choose the tool profile. Tool activity is shown inline. |
| **Personas** | Edit or create personas: name, role, personality, speaking style, model, vote weight, and a **live face editor** (colours, hair style, face shape, glasses, beard…) with all seven expressions. |
| **Tools** | Search and filter all 78 tools by category, risk and profile. |
| **Safety** | Run the safety fire drills and the setup doctor from the browser. |
| **Guide ↗** | The Agent Builder Knowledge Suite (also at `docs/agent_builder_suite.html`). |

When an agent wants a risky tool (shell, Python, delete…), an **Allow / Deny** box appears with the exact
arguments. No answer within 3 minutes means **Deny**. **Stop** in the top bar halts the current job at the
next safe point and rolls its history back cleanly.

## How it's built

```
browser  ──fetch + X-Agent-Token──►  gui/server.py  (127.0.0.1 only, stdlib http.server)
   ▲                                     │
   └──── Server-Sent Events ◄── gui/jobs.py EventBus ◄── agents / council (background thread)
                                         │
                              ApprovalBroker ◄── risky tool asks → browser Allow/Deny
```

Analogy: a TV studio control room. The **EventBus** is the live feed to every open tab, the
**ApprovalBroker** is the producer's headset (agents ask, you answer), and the **JobManager** is the
floor manager running one show at a time.

| Protection | Why |
|---|---|
| Listens on `127.0.0.1` only | Unreachable from your network |
| Per-launch random token on every request | Other programs and pages can't use the API |
| `Host` and `Origin` checks | Blocks DNS rebinding and cross-site requests from websites you visit |
| Strict Content-Security-Policy, no inline scripts | Injected script can't run |
| Model output is always rendered as **text** | A model can't inject HTML into the page |
| Only whitelisted static files; 1 MB body cap | No path traversal, no memory abuse |
| Secrets redacted from the live event feed | API keys never reach the browser |

The front end is plain HTML, CSS and JavaScript with no libraries or CDNs (`gui/static/`), so it works offline.
These are tested in `tests/test_gui.py`, and `scripts/ui_smoke.py` drives it in a real headless browser.

## Personas

A persona is a council member with a character. Built-ins: **Sage** (chair), **Vex** (skeptic) and **Nova**
(researcher). Your own go in `./personas/` (see [personas/README.md](../personas/README.md)).

```json
{"id": "atlas", "name": "Atlas", "role": "engineer", "title": "The Builder",
 "personality": "Pragmatic and hands-on.", "speaking_style": "short sentences, concrete steps",
 "greeting": "Show me the constraints.", "backend": "local:llama3.1:8b", "weight": 1.0,
 "face": {"skin": "#b97a4f", "hair_style": "short", "glasses": true}, "image": null}
```

What the model sees: the **role's** persona (what it cares about), then the **character's** personality
and speaking style, with an instruction that style must never get in the way of accuracy.

Use them anywhere:
```bash
python -m hybrid_agent council --personas sage,vex,nova -p "..."
```
```json
{"protocol": "debate", "personas": ["sage", "vex", "nova"]}
```

## Faces

Faces are drawn procedurally as SVG (`personas/faces.py`): no image files, no downloads, no AI image service.

Analogy: a paper-doll kit. The kit (skin, hair, eyes, shirt, backdrop colours; hair style; face shape;
mouth; glasses, beard, earrings, freckles, blush) is fixed per persona. The **expression** swaps the brows,
eyes and mouth: `neutral`, `thinking` (eyes up, thought bubble), `speaking` (open mouth, animated),
`happy`, `concerned`, `surprised`, `skeptical`.

Every colour and option is validated before it's drawn, so a hand-edited persona file can't inject markup.
The GUI animates blinking and talking with CSS, and turns animation off if your system asks for reduced motion.

## Groundwork: where to take it next

| Next step | How it plugs in |
|---|---|
| **Portraits** (your own art or AI-generated) | Set `"image": "atlas.png"` (a file in `./personas/`). The GUI shows it instead of the drawn face |
| **Expression-matched portraits** | Extend `image` to a map `{"neutral": "atlas.png", "happy": "atlas-happy.png", ...}`; `setFace()` in `app.js` already switches by expression |
| **Voices (text-to-speech)** | Add `"voice"` to the persona; on `member_done`, send the text to a local TTS (e.g. Piper) and play it. The *speaking* face already animates while a member talks |
| **Lip-sync / animated avatars** | Replace the `<svg>` in `.face` with a canvas or Live2D/VRM component that reads the same state events |
| **Per-persona memory** | Prefix memory keys with the persona id, or give each persona its own memory file |
| **Streaming text** | Stream tokens from the local backend and publish them as events, so speech bubbles fill in live |
