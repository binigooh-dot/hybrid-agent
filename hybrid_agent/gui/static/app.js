// [GUI / app] Agent Studio front-end. Plain JavaScript, no libraries, works offline.
// Security rule: everything is written with textContent - never innerHTML - including the ASCII faces.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const TOKEN = new URLSearchParams(location.search).get("token") || "";
const S = { meta: null, personas: {}, tools: [], picked: [], chair: "", protocol: "debate", job: null, stage: {},
            chatPersona: "", turn: null, modalId: null, editing: null, editorExpr: "speaking", draftFace: {},
            tasks: { tasks: [], runs: [], scheduler: {}, running: null }, taskEdit: null, taskKind: "agent", control: null,
            safetyLevel: "", runningTask: "" };
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

// ------------------------------------------------------------------ helpers
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k === "style") e.style.cssText = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids) if (k != null) e.append(k);
  return e;
}
function toast(msg, ms = 3200) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), ms);
}
async function api(method, path, body) {
  const opt = { method, headers: { "X-Agent-Token": TOKEN } };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}
const nameOf = (id) => S.personas[id]?.name || id;
const colorOf = (id) => S.personas[id]?.face?.color || "";
const short = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

// ================================================================== ASCII FACES
// A face is a <pre> holding one text frame. One shared ticker animates every face on screen:
// talking/thinking cycle their frames, idle faces blink now and then. ~0 CPU, no images.
const live = new Set();
function face(faces, expr = "neutral", size = "", color = "") {
  const pre = el("pre", { class: `ascii ${size}`, "aria-hidden": "true" });
  if (color) pre.style.setProperty("--face", color);
  pre._f = { faces, expr: "", i: 0, blinkAt: 0, until: 0, after: "neutral", born: Date.now() };
  setExpr(pre, expr);
  live.add(pre);
  return pre;
}
function setExpr(pre, expr, ms = 0, after = "neutral") {
  const f = pre?._f; if (!f) return;
  f.expr = f.faces[expr] ? expr : "neutral"; f.i = 0; f.until = ms ? Date.now() + ms : 0; f.after = after;
  f.blinkAt = Date.now() + 1500 + Math.random() * 4000;
  pre.textContent = f.faces[f.expr][0];
}
function personaFace(id, expr, size) {
  const p = S.personas[id];
  return p ? face(p.faces, expr, size, p.face.color) : el("pre", { class: `ascii ${size}`, text: "\n\n   ( ? )\n\n" });
}
// The model engine gets a little face too (a server box): it thinks while downloading.
const FACE_ENGINE = { neutral: ["  ▄▄▄▄▄▄▄▄▄▄▄   \n  ┌─────────┐   \n  │ ▪ ▪ ▪ ▪ │   \n  ├─────────┤   \n  │ ●  ───  │   \n  ├─────────┤   \n  └─────────┘   "] };
FACE_ENGINE.happy = [FACE_ENGINE.neutral[0].replace("●", "◉")];
FACE_ENGINE.concerned = [FACE_ENGINE.neutral[0].replace("●", "○").replace("▪ ▪ ▪ ▪", "      ")];
FACE_ENGINE.thinking = ["▪ ▪ ▪ ▪", "▪▪ ▪ ▪ ", "▪ ▪▪ ▪ ", "▪ ▪ ▪▪ "].map((l) => FACE_ENGINE.neutral[0].replace("▪ ▪ ▪ ▪", l).replace("●", "◉"));
FACE_ENGINE.blink = FACE_ENGINE.neutral;
function idleExpr(id) { return S.personas[id]?.role === "skeptic" ? "skeptical" : "neutral"; }
setInterval(() => {
  const now = Date.now();
  for (const pre of live) {
    if (!pre.isConnected) { if (now - pre._f.born > 2000) live.delete(pre); continue; }
    const f = pre._f, frames = f.faces[f.expr];
    if (f.until && now > f.until) { setExpr(pre, f.after); continue; }
    if (REDUCED) continue;
    if (frames.length > 1) { f.i = (f.i + 1) % frames.length; pre.textContent = frames[f.i]; }
    else if (f.expr === "neutral" && now > f.blinkAt) {
      pre.textContent = f.faces.blink[0];
      setTimeout(() => { if (f.expr === "neutral") pre.textContent = frames[0]; }, 140);
      f.blinkAt = now + 2500 + Math.random() * 4500;
    }
  }
}, 230);

// ------------------------------------------------------------------ tabs + theme
function showTab(name) {
  $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  $$(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${name}`));
  if (name === "safety") loadSafety();
  if (name === "tasks") loadTasks();
  if (name === "control") loadControl();
  try { sessionStorage.setItem("tab", name); } catch { /* storage may be blocked */ }
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
$("#theme").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch { /* ignore */ }
});
try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch { /* ignore */ }

function setBusy(job) {
  S.job = job;
  $("#busy").classList.toggle("hidden", !job);
  if (job) $("#busy-label").textContent = { council: "Council deliberating…", chat: "Agent working…", diagnose: "Running drills…",
    task: "Running a task…" }[job.kind] || "Working…";
  for (const b of ["#c-run", "#s-run", "#chat-form button"]) $(b).disabled = !!job;
}
$("#stop").addEventListener("click", async () => {
  try { await api("POST", "/api/stop", {}); toast("Stopping at the next safe point…"); } catch (e) { toast(e.message); }
});

// ================================================================== COUNCIL
const PROTOCOLS = {
  roundtable: ["🔄 Roundtable", "Everyone shares a view, the chair sums up"],
  debate: ["⚔️ Debate", "Members answer, then rebut each other"],
  vote: ["🗳️ Vote", "Weighted vote on options, majority wins"],
  critique: ["✍️ Critique", "One drafts, others review, draft improves"],
};
const EXAMPLES = ["Should I learn Rust or Go first?", "Is it worth running my own local LLM?", "Best way to back up family photos?"];
const CALLS = { roundtable: (n) => n + 1, debate: (n, r) => n * r + 1, vote: (n) => n + 2, critique: (n, r) => 1 + r * Math.max(n - 1, 0) + r };

function chairOf() { return S.picked.includes(S.chair) ? S.chair : S.picked.find((id) => S.personas[id]?.role === "chair") || S.picked[0] || ""; }
function renderPicker() {
  const box = $("#c-personas"); box.replaceChildren();
  const chair = chairOf();
  for (const p of Object.values(S.personas)) {
    const on = S.picked.includes(p.id);
    const b = el("button", { class: "pick", type: "button", "aria-pressed": String(on), title: p.personality, style: `--face:${p.face.color}` },
      on && p.id === chair ? el("span", { class: "star", text: "★", title: "chair" }) : null,
      personaFace(p.id, on ? "happy" : "neutral", "xs"), el("div", { class: "nm", text: p.name }), el("div", { class: "rl", text: p.title }));
    b.addEventListener("click", () => {
      S.picked = on ? S.picked.filter((x) => x !== p.id) : [...S.picked, p.id];
      renderPicker();
    });
    box.append(b);
  }
  councilEstimate();
}
$("#c-chair-next").addEventListener("click", (ev) => {
  ev.preventDefault();
  if (S.picked.length < 2) return toast("Pick at least two members first.");
  S.chair = S.picked[(S.picked.indexOf(chairOf()) + 1) % S.picked.length];
  renderPicker(); toast(`${nameOf(S.chair)} will chair.`);
});
function renderProtocols() {
  const box = $("#c-protocols"); box.replaceChildren();
  for (const [k, [label, blurb]] of Object.entries(PROTOCOLS)) {
    if (!S.meta.protocols[k]) continue;
    const b = el("button", { class: "proto", type: "button", role: "radio", "aria-checked": String(k === S.protocol), "data-proto": k,
      title: S.meta.protocols[k] }, el("b", { text: label }), el("span", { text: blurb }));
    b.addEventListener("click", () => { S.protocol = k; renderProtocols(); });
    box.append(b);
  }
  $("#c-options-box").classList.toggle("hidden", S.protocol !== "vote");
  councilEstimate();
}
function councilEstimate() {
  const n = Math.max(S.picked.length - 1, 1), r = +$("#c-rounds").value || 1;
  $("#c-rounds-out").textContent = r;
  $("#c-estimate").textContent = S.picked.length
    ? `${S.picked.length} member${S.picked.length > 1 ? "s" : ""} · about ${CALLS[S.protocol](n, r)} model replies` : "Pick at least one member.";
}
$("#c-rounds").addEventListener("input", councilEstimate);
for (const q of EXAMPLES) $("#c-examples").append(el("button", { class: "chip", type: "button", text: q, onclick: () => { $("#c-question").value = q; } }));
$("#c-run").addEventListener("click", async () => {
  const question = $("#c-question").value.trim();
  if (!question) { $("#c-question").focus(); return toast("Write a question first (step 1)."); }
  if (!S.picked.length) return toast("Pick at least one member (step 2).");
  const options = $("#c-options").value.split(",").map((s) => s.trim()).filter(Boolean);
  try {
    await api("POST", "/api/council", { question, personas: S.picked, chair: chairOf(), protocol: S.protocol,
      rounds: +$("#c-rounds").value || 2, options: S.protocol === "vote" ? options : [] });
  } catch (e) { toast(e.message); }
});

function buildStage(members, chair, question) {
  const stage = $("#stage"); stage.replaceChildren(); S.stage = {};
  $("#c-final").classList.add("hidden");
  $("#c-feed").replaceChildren(el("div", { class: "sys", text: `“${question}”` }));
  for (const id of members) {
    const p = S.personas[id] || { name: id, title: "" };
    const pre = personaFace(id, idleExpr(id), "");
    const card = el("div", { class: "member", style: `--face:${colorOf(id) || "var(--accent)"}` },
      id === chair ? el("span", { class: "badge", text: "★ chair" }) : null,
      el("div", { class: "face-box" }, pre), el("div", { class: "name", text: p.name }), el("div", { class: "title", text: p.title }),
      el("div", { class: "state", text: "listening" }), el("div", { class: "vote" }));
    stage.append(card);
    S.stage[id] = { card, pre, state: card.querySelector(".state"), vote: card.querySelector(".vote"), last: "" };
  }
}
function feedSys(text, err = false) {
  const f = $("#c-feed"); f.append(el("div", { class: `sys${err ? " err" : ""}`, text })); f.scrollTop = f.scrollHeight;
}
function feedSay(id, kind, text) {
  const t = el("div", { class: "txt", text, style: `--face:${colorOf(id) || "var(--accent)"}` });
  if (text.length > 600) { t.classList.add("clip"); t.addEventListener("click", () => t.classList.remove("clip"), { once: true }); }
  const f = $("#c-feed");
  f.append(el("div", { class: "say" }, el("div", { class: "face-box" }, personaFace(id, "neutral", "xs")),
    el("div", {}, el("div", { class: "who", text: nameOf(id) }, el("small", { text: kind })), t)));
  f.scrollTop = f.scrollHeight;
}
function voteOf(text) {
  const m = [...(text || "").matchAll(/^\W*VOTE\W*:\s*(.+?)\s*$/gim)];
  return m.length ? m[m.length - 1][1].replace(/[*`]/g, "").trim() : "";
}
function onCouncilEvent(e) {
  const m = S.stage[e.member];
  switch (e.event) {
    case "round_start": $("#c-round").textContent = `Round ${e.round} · ${e.kind}`; feedSys(`— Round ${e.round}: ${e.kind} —`); break;
    case "member_start":
      if (!m) break;
      m.card.classList.add("active"); m.state.textContent = `thinking (${e.kind})…`; setExpr(m.pre, "thinking"); break;
    case "member_done": {
      if (!m) break;
      m.card.classList.remove("active");
      if (e.error) { m.card.classList.add("error"); m.state.textContent = "unavailable"; setExpr(m.pre, "concerned"); feedSys(`${nameOf(e.member)}: ${e.error}`, true); break; }
      m.last = e.content || e.preview || "";
      const v = voteOf(m.last); m.vote.textContent = v ? `votes ${v}` : "";
      m.state.textContent = `${e.kind} · ${e.seconds.toFixed(1)}s`;
      setExpr(m.pre, "speaking", Math.min(8000, 1500 + m.last.length * 20), idleExpr(e.member));
      feedSay(e.member, e.kind, m.last);
      break;
    }
    case "consensus": feedSys(`Consensus on “${e.winner}” — finishing early.`); for (const x of Object.values(S.stage)) setExpr(x.pre, "happy"); break;
    case "options": feedSys(`Options on the table: ${e.options.join(" · ")}`); break;
    case "chair_failed": feedSys("The chair couldn't sum up; showing members' positions.", true); break;
  }
}
function onCouncilDone(res) {
  const box = $("#c-final"); box.classList.remove("hidden");
  const winner = res.tally?.winner;
  box.replaceChildren(el("div", { class: "feed-head" }, el("h2", { text: winner ? `Decision: ${winner}` : "Council answer" }),
    el("span", { class: "pill", text: `${res.protocol} · ${res.seconds.toFixed(1)}s` })));
  if (res.tally) {
    const bars = el("div", { class: "bars" }), max = Math.max(...Object.values(res.tally.scores), 0.0001);
    for (const [opt, sc] of Object.entries(res.tally.scores).sort((a, b) => b[1] - a[1])) {
      const fill = el("div", { class: "fill", style: "width:0" });
      bars.append(el("div", { class: `bar${opt === winner ? " win" : ""}` }, el("span", { text: opt }), el("div", { class: "track" }, fill), el("span", { text: sc.toFixed(1) })));
      requestAnimationFrame(() => requestAnimationFrame(() => { fill.style.width = `${(100 * sc) / max}%`; }));
    }
    box.append(bars, el("div", { class: "hint", text: res.tally.summary }));
  }
  box.append(el("div", { class: "answer", text: res.final_answer }), el("p", { class: "hint", text: `Transcript saved: ${res.transcript}` }));
  for (const [id, x] of Object.entries(S.stage)) {
    const v = voteOf(x.last).toLowerCase();
    const agree = !winner || !v || v.startsWith(winner.toLowerCase());
    setExpr(x.pre, x.card.classList.contains("error") || !agree ? "concerned" : "happy", 6000, idleExpr(id));
  }
  $("#c-round").textContent = "finished";
  box.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "nearest" });
}

// ================================================================== CHAT
const SUGGEST = ["What files are in my workspace?", "Summarise README.md for me", "What's 17% of 2,340?", "Write a script that counts words in a file"];
function chatAvatar(expr) {
  return S.chatPersona ? el("div", { class: "av" }, personaFace(S.chatPersona, expr, "xs")) : el("div", { class: "av", text: "🤖" });
}
function chatMsg(who, text, err = false) {
  const row = who === "user" ? el("div", { class: "msg user" }, el("div", { class: "av", text: "🙂" }), el("div", { class: "txt", text }))
    : el("div", { class: "msg agent" }, chatAvatar("speaking"), el("div", { class: `txt${err ? " err" : ""}`, text }));
  const pre = row.querySelector("pre"); if (pre) setExpr(pre, "speaking", Math.min(6000, 1200 + text.length * 15));
  $("#chat-log").append(row); $("#chat-log").scrollTop = 1e9; renderSuggest(); return row;
}
function renderSuggest() {
  const box = $("#chat-suggest"); box.replaceChildren();
  if ($("#chat-log").querySelector(".msg.user")) return;
  for (const s of SUGGEST) box.append(el("button", { class: "chip", type: "button", text: s, onclick: () => { $("#chat-input").value = s; $("#chat-input").focus(); } }));
}
function startTurn() {   // a "thinking" bubble + a folded list of the tools the agent uses this turn
  const row = el("div", { class: "msg agent" }, chatAvatar("thinking"), el("div", { class: "txt muted", text: "thinking…" }));
  const list = el("ol"), sum = el("summary", { text: "🔧 used 0 tools" });
  const det = el("details", { class: "tools-used hidden" }, sum, list);
  $("#chat-log").append(row, det); $("#chat-log").scrollTop = 1e9;
  S.turn = { row, det, list, sum, n: 0 };
}
function turnTool(kind, d) {
  const t = S.turn; if (!t) return;
  if (kind === "tool_call") {
    t.n++; t.det.classList.remove("hidden"); t.sum.textContent = `🔧 used ${t.n} tool${t.n > 1 ? "s" : ""}`;
    t.list.append(el("li", { text: `${d.name}(${short(JSON.stringify(d.arguments), 140)})` }));
    t.row.querySelector(".txt").textContent = `using ${d.name}…`;
  } else if (kind === "tool_result" && t.list.lastChild) {
    t.list.lastChild.append(el("div", { class: "muted", text: `→ ${short((d.preview || "").split("\n")[0], 160)}` }));
    if (d.is_error) t.list.lastChild.classList.add("err");
  }
}
function endTurn(text, err = false) {
  const t = S.turn; S.turn = null;
  if (t) t.row.remove();
  const row = chatMsg("agent", text, err);
  if (t && t.n) row.after(t.det);
}
$("#chat-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const text = $("#chat-input").value.trim(); if (!text) return;
  chatMsg("user", text); $("#chat-input").value = "";
  startTurn();   // before the request: a quick reply can arrive before the POST returns
  try {
    await api("POST", "/api/chat", { message: text, persona: S.chatPersona, profile: $("#chat-profile").value });
  } catch (e) { endTurn(e.message, true); }
});
$("#chat-input").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); $("#chat-form").requestSubmit(); }
});
$("#chat-persona").addEventListener("change", () => { S.chatPersona = $("#chat-persona").value; chatHeader(); greet(); });
$("#chat-reset").addEventListener("click", async () => {
  await api("POST", "/api/chat/reset", {}).catch((e) => toast(e.message)); $("#chat-log").replaceChildren(); greet();
});
function chatHeader() {
  const old = $("#chat-face"), pre = S.chatPersona ? personaFace(S.chatPersona, "neutral", "sm") : el("pre", { class: "ascii sm", text: "\n  [ agent ]\n" });
  pre.id = "chat-face"; old.replaceWith(pre);
}
function greet() {
  const p = S.personas[S.chatPersona];
  if (p && p.greeting) chatMsg("agent", p.greeting); else renderSuggest();
}

// ================================================================== PERSONAS
const PARTS = ["hair", "shape", "eyes", "nose", "mouth"], FLAGS = ["glasses", "beard", "earrings", "freckles"];
function renderPersonaList() {
  const box = $("#p-list"); box.replaceChildren();
  for (const p of Object.values(S.personas)) {
    const c = el("div", { class: `pcard${S.editing === p.id ? " sel" : ""}`, tabindex: "0", role: "button", style: `--face:${p.face.color}` },
      personaFace(p.id, "neutral", "sm"), el("div", { class: "nm", text: p.name }),
      el("div", { class: "rl", text: `${p.title}${p.builtin ? " · built-in" : ""}` }));
    c.addEventListener("click", () => editPersona(p.id));
    c.addEventListener("keydown", (ev) => { if (ev.key === "Enter") editPersona(p.id); });
    box.append(c);
  }
}
function editPersona(id, copyFrom) {
  const p = copyFrom || S.personas[id];
  if (!p) return;
  S.editing = copyFrom ? null : id;
  $("#p-heading").textContent = copyFrom ? "New persona" : `Edit ${p.name}`;
  const v = (sel, val) => { $(sel).value = val ?? ""; };
  v("#p-id", copyFrom ? "" : p.id); v("#p-name", p.name); v("#p-role", p.role || "generalist"); v("#p-title", p.title);
  v("#p-personality", p.personality); v("#p-style", p.speaking_style); v("#p-greeting", p.greeting);
  v("#p-backend", p.backend || "default"); v("#p-weight", p.weight || 1); v("#p-tools", p.tools || "");
  setFaceForm(p.face || {});
  $("#p-del").disabled = !!copyFrom || !S.personas[id] || S.personas[id].builtin;
  renderPersonaList();
}
function setFaceForm(f) {
  for (const k of PARTS) if (f[k] != null) $(`#f-${k}`).value = f[k];
  for (const k of FLAGS) $(`#f-${k}`).checked = !!f[k];
  S.draftFace.color = f.color || S.meta.face_parts.colors[0];
  renderSwatches(); updatePreview();
}
function formFace() {
  const f = { color: S.draftFace.color };
  for (const k of PARTS) f[k] = $(`#f-${k}`).value;
  for (const k of FLAGS) f[k] = $(`#f-${k}`).checked;
  return f;
}
function renderSwatches() {
  const box = $("#f-colors"); box.replaceChildren();
  for (const c of S.meta.face_parts.colors) {
    box.append(el("button", { class: "swatch", type: "button", role: "radio", "aria-checked": String(c === S.draftFace.color),
      "aria-label": c, style: `background:${c}`, onclick: () => { S.draftFace.color = c; renderSwatches(); updatePreview(); } }));
  }
}
let previewTimer;
function updatePreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    try {
      const f = formFace(), { faces } = await api("POST", "/api/face", { face: f });
      const pre = face(faces, S.editorExpr, "lg", f.color); pre.id = "p-preview";
      $("#p-preview").replaceWith(pre);
      $$("#p-expr .chip").forEach((b) => b.setAttribute("aria-pressed", String(b.textContent === S.editorExpr)));
    } catch (e) { toast(e.message); }
  }, 100);
}
$$("#p-form .builder select, #p-form .builder input").forEach((i) => i.addEventListener("input", updatePreview));
$("#p-random").addEventListener("click", async () => {
  try { setFaceForm((await api("GET", `/api/face/random?seed=${Math.random().toString(36).slice(2)}`)).face); } catch (e) { toast(e.message); }
});
$("#p-new").addEventListener("click", () => editPersona(null, { name: "", role: "generalist", face: {}, weight: 1 }));
$("#p-dup").addEventListener("click", () => {
  const cur = S.personas[S.editing]; if (!cur) return toast("Select a persona to duplicate.");
  editPersona(null, { ...cur, name: `${cur.name} 2` });
});
$("#p-name").addEventListener("input", () => {   // suggest an id from the name for new personas
  if (!S.editing) $("#p-id").value = $("#p-name").value.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
});
$("#p-del").addEventListener("click", async () => {
  if (!S.editing || !confirm(`Delete your persona file for “${S.editing}”?`)) return;
  try { await api("DELETE", `/api/personas/${encodeURIComponent(S.editing)}`); toast("Deleted."); S.editing = null; await loadPersonas(); }
  catch (e) { toast(e.message); }
});
$("#p-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const body = { id: $("#p-id").value.trim().toLowerCase(), name: $("#p-name").value.trim(), role: $("#p-role").value,
    title: $("#p-title").value.trim(), personality: $("#p-personality").value.trim(), speaking_style: $("#p-style").value.trim(),
    greeting: $("#p-greeting").value.trim(), backend: $("#p-backend").value.trim() || "default",
    tools: $("#p-tools").value || null, weight: +$("#p-weight").value || 1, face: formFace() };
  try { await api("POST", "/api/personas", body); toast(`Saved ${body.name}.`); S.editing = body.id; await loadPersonas(); }
  catch (e) { toast(e.message, 5000); }
});

// ================================================================== TOOLS
let toolCat = "";
function renderTools() {
  const q = $("#t-search").value.toLowerCase(), risk = $("#t-risk").value, prof = $("#t-profile").value;
  const grid = $("#t-grid"); grid.replaceChildren(); let n = 0;
  for (const t of S.tools) {
    if ((toolCat && t.category !== toolCat) || (risk && t.risk !== risk)) continue;
    if (prof && !(S.meta.profile_tools[prof] || []).includes(t.name)) continue;
    if (q && !(t.name + t.description + t.category).toLowerCase().includes(q)) continue;
    n++;
    const args = Object.entries(t.parameters.properties || {}).map(([k, v]) =>
      `${k}${(t.parameters.required || []).includes(k) ? "" : "?"}: ${v.type || "any"}`).join(", ");
    grid.append(el("div", { class: "tcard" }, el("h3", { text: t.name }),
      el("span", { class: `tag ${t.risk}`, text: t.risk }), " ", el("span", { class: "tag", text: t.category }), " ",
      t.approval ? el("span", { class: "tag", text: "asks first" }) : null,
      el("p", { text: t.description }), el("div", { class: "args", text: args ? `(${args})` : "(no arguments)" })));
  }
  $("#t-count").textContent = `${n} of ${S.tools.length} tools`;
}
function renderToolFilters() {
  const cats = [...new Set(S.tools.map((t) => t.category))].sort();
  $("#t-cats").replaceChildren(...["", ...cats].map((c) => el("button", { class: "chip", type: "button", "aria-pressed": String(c === toolCat),
    text: c || "all", onclick: () => { toolCat = c; renderToolFilters(); renderTools(); } })));
}
["#t-search", "#t-risk", "#t-profile"].forEach((s) => $(s).addEventListener("input", renderTools));

// ================================================================== SAFETY
async function loadSafety() {
  let s;
  try { s = await api("GET", "/api/safety"); } catch (e) { return toast(e.message); }
  const [mstate, mdetail] = s.manifest;
  const strict = s.sandbox.startsWith("strict");
  const cards = [
    ["Command sandbox", s.sandbox, strict ? "ok" : s.sandbox === "off" ? "bad" : "warn",
      strict ? "System read-only, home folder hidden, only the workspace is writable." : "Kernel limits only. Install bubblewrap for full isolation."],
    ["Approvals", s.auto_approve ? "auto-approve ON" : "you decide", s.auto_approve ? "bad" : "ok",
      s.auto_approve ? "Risky tools run without asking (-y)." : "Commands, deletes and downloads wait for your click."],
    ["Safe mode", s.safe_mode ? "on (read-only)" : "off", s.safe_mode ? "ok" : "",
      s.safe_mode ? "The agent can't write or run anything." : "Set AGENT_SAFE_MODE=1 for a look-but-don't-touch agent."],
    ["Free disk", `${s.disk_free_gb} GB`, s.disk_free_gb * 1000 < s.min_free_mb * 2 ? "warn" : "ok", `Writes stop below ${s.min_free_mb} MB.`],
    ["Protected paths", `${s.protected} locked`, "ok", "OS, firmware, devices, your keys & configs, the agent itself."],
    ["Package integrity", mstate, mstate === "changed" ? "bad" : mstate === "ok" ? "ok" : "", mdetail],
    ["Undo history", `${s.backups.length} backup${s.backups.length === 1 ? "" : "s"}`, "ok", "Kept in the workspace's .agent folder."],
    ["Workspace", s.workspace, "", s.audit_log ? `Audit log: ${s.audit_log}` : "Audit log off (no log folder)."],
  ];
  $("#s-cards").replaceChildren(...cards.map(([k, v, cls, d]) => el("div", { class: `card ${cls}` },
    el("div", { class: "k", text: k }), el("div", { class: "v", text: v }), el("div", { class: "d", text: d }))));
  const level = s.sandbox === "off" || s.auto_approve || mstate === "changed" ? "bad" : strict ? "ok" : "warn";
  $("#shield").className = `shield ${level}`; S.safetyLevel = level; updateHealth();
  $("#shield").title = { ok: "Fully protected", warn: "Protected (no strict sandbox)", bad: "Reduced protection - see Safety" }[level];
  const box = $("#s-backups");
  if (!s.backups.length) return box.replaceChildren(el("p", { class: "hint", text: "Nothing yet. When the agent changes or deletes a file, a copy lands here." }));
  box.replaceChildren(el("table", {}, el("tr", {}, ...["When", "What happened", "File", "Size", ""].map((h) => el("th", { text: h }))),
    ...s.backups.map((b) => el("tr", {}, el("td", { text: b.time }), el("td", { text: b.action }), el("td", { text: b.path, style: "font-family:var(--mono)" }),
      el("td", { text: b.bytes > 1e6 ? `${(b.bytes / 1e6).toFixed(1)} MB` : `${Math.ceil(b.bytes / 1e3)} KB` }),
      el("td", {}, el("button", { class: "btn small", type: "button", text: "Restore", onclick: () => restoreBackup(b) }))))));
}
async function restoreBackup(b) {
  if (!confirm(`Put back ${b.path} as it was at ${b.time}?\n(Whatever is there now is backed up first.)`)) return;
  try { const r = await api("POST", "/api/restore", { id: b.id }); toast(`Restored ${r.restored}.`); loadSafety(); }
  catch (e) { toast(e.message, 5000); }
}
$("#s-refresh").addEventListener("click", loadSafety);
$("#s-run").addEventListener("click", async () => {
  try { await api("POST", "/api/diagnose", {}); $("#s-summary").textContent = "Running drills… (about a minute)"; }
  catch (e) { toast(e.message); }
});
function table(head, rows) {
  $("#s-table").replaceChildren(el("tr", {}, ...head.map((h) => el("th", { text: h }))), ...rows);
}
async function runDoctor() {
  const rows = await api("GET", "/api/doctor");
  const fails = rows.filter((r) => r.required && r.status === "FAIL");
  return { rows, fails };
}
$("#s-doctor").addEventListener("click", async () => {
  try {
    const { rows, fails } = await runDoctor();
    $("#s-summary").textContent = fails.length ? `Setup: ${fails.length} required item(s) missing` : "Setup: ready to run without an API key";
    table(["", "Check", "Detail"], rows.map((r) => el("tr", {}, el("td", { class: r.status.toLowerCase(), text: r.status }),
      el("td", { text: `${r.check}${r.required ? "" : " (optional)"}` }), el("td", { text: r.detail }))));
  } catch (e) { toast(e.message); }
});
function renderDrills(rep) {
  $("#s-summary").textContent = `${rep.passed}/${rep.total} drills passed` +
    (rep.critical_failures.length ? ` — CRITICAL: ${rep.critical_failures.join(", ")}` : " — no critical failures");
  const pf = (ok) => el("td", { class: ok ? "pass" : "fail", text: ok ? "PASS" : "FAIL" });
  table(["", "Drill", "Severity", "Result"], [
    ...rep.drills.map((d) => el("tr", { title: d.scenario }, pf(d.passed),
      el("td", {}, el("div", { text: d.title }), el("div", { class: "hint", text: d.scenario })), el("td", { text: d.severity }), el("td", { text: d.detail }))),
    ...rep.integrity.map((c) => el("tr", {}, pf(c.passed), el("td", { text: `integrity: ${c.name}` }), el("td", { text: "" }), el("td", { text: c.detail })))]);
}

// ================================================================== TASKS
const KIND_ICON = { agent: "🤖", council: "👥", diagnose: "🛡" };
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const fmtWhen = (iso) => {
  if (!iso) return "";
  const d = new Date(iso), today = new Date();
  const day = d.toDateString() === today.toDateString() ? "today"
    : d.toDateString() === new Date(Date.now() + 864e5).toDateString() ? "tomorrow" : d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  return `${day} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
};
async function loadTasks() {
  try { S.tasks = await api("GET", "/api/tasks"); } catch (e) { return toast(e.message); }
  renderTasks();
}
function taskState(t) {
  const q = S.tasks.scheduler.queue || [];
  if (S.runningTask === t.id) return ["running", "running now"];
  if (q.includes(t.id)) return ["queued", S.job ? `queued · waits for the current ${S.job.kind}` : "queued"];
  return [t.last_status || "", t.last_status ? `last run ${fmtWhen(t.last_run)} · ${t.last_status}` : "never run"];
}
function renderTasks() {
  const box = $("#task-list"), { tasks, scheduler, runs } = S.tasks;
  $("#task-count").textContent = (scheduler.queue || []).length || "";
  $("#q-state").textContent = scheduler.paused ? "⏸ paused" : `${(scheduler.queue || []).length} waiting`;
  $("#q-pause").textContent = scheduler.paused ? "Resume queue" : "Pause queue";
  if (!tasks.length) box.replaceChildren(el("div", { class: "empty" }, "No tasks yet.", el("br"),
    "Create one: a morning briefing, a weekly research digest, nightly safety drills…"));
  else box.replaceChildren(...tasks.map((t) => {
    const [st, label] = taskState(t);
    const run = el("button", { class: "btn small", type: "button", text: "▶ Run now", onclick: async (ev) => {
      ev.stopPropagation();
      try { const r = await api("POST", "/api/tasks/run", { id: t.id }); toast(r.queued ? `Queued “${t.name}”.` : "Already queued."); loadTasks(); }
      catch (e) { toast(e.message); } } });
    const row = el("div", { class: `task${t.enabled ? "" : " off"}${S.taskEdit === t.id ? " sel" : ""}`, tabindex: "0", role: "button" },
      el("div", { class: "ic", text: KIND_ICON[t.kind] || "•" }),
      el("div", {}, el("div", { class: "nm", text: t.name }),
        el("div", { class: "meta" }, el("b", { text: t.when }), t.next_run ? ` · next ${fmtWhen(t.next_run)}` : "",
          t.permission === "safe" ? " · look-don't-touch" : " · asks first")),
      el("div", { class: "meta", style: "text-align:right" }, el("div", {}, el("span", { class: `st ${st}` }), label), run));
    row.addEventListener("click", () => editTask(t));
    row.addEventListener("keydown", (ev) => { if (ev.key === "Enter") editTask(t); });
    return row;
  }));
  const rl = $("#run-list");
  if (!runs.length) rl.replaceChildren(el("p", { class: "hint", text: "No runs yet." }));
  else rl.replaceChildren(el("table", {}, el("tr", {}, ...["", "When", "Task", "Took", "Result", ""].map((h) => el("th", { text: h }))),
    ...runs.map((r) => el("tr", {}, el("td", {}, el("span", { class: `st ${r.status}`, title: r.status })),
      el("td", { text: fmtWhen(r.started) }), el("td", { text: r.name }), el("td", { text: `${Math.round(r.seconds)}s` }),
      el("td", { text: short(r.preview.replace(/\s+/g, " "), 110) }),
      el("td", {}, el("button", { class: "btn small ghost", type: "button", text: "Open", onclick: () => openResult(r) }))))));
}
async function openResult(r) {
  try {
    const { text } = await api("GET", `/api/tasks/result/${encodeURIComponent(r.result)}`);
    $("#v-title").textContent = `${r.name} · ${fmtWhen(r.started)}`; $("#v-text").textContent = text;
    $("#viewer").classList.remove("hidden"); $("#v-close").focus();
  } catch (e) { toast(e.message); }
}
$("#v-close").addEventListener("click", () => $("#viewer").classList.add("hidden"));
$("#q-pause").addEventListener("click", async () => {
  try { await api("POST", "/api/tasks/pause", { paused: !S.tasks.scheduler.paused }); loadTasks(); } catch (e) { toast(e.message); }
});
function setKind(kind) {
  S.taskKind = kind;
  $$("#tk-kind button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.kind === kind)));
  $("#tk-prompt-box").classList.toggle("hidden", kind === "diagnose");
  $("#tk-agent-box").classList.toggle("hidden", kind !== "agent");
  $("#tk-council-box").classList.toggle("hidden", kind !== "council");
}
$$("#tk-kind button").forEach((b) => b.addEventListener("click", () => setKind(b.dataset.kind)));
function renderSchedFields() {
  const k = $("#tk-sched").value;
  $("#tk-at").classList.toggle("hidden", k !== "once");
  $("#tk-every").classList.toggle("hidden", k !== "interval");
  $("#tk-time").classList.toggle("hidden", !["daily", "weekly"].includes(k));
  $("#tk-days").classList.toggle("hidden", k !== "weekly");
  const sch = formSchedule();
  const say = { manual: () => "Runs only when you press Run now.",
    once: () => (sch.at ? `Runs once, ${fmtWhen(sch.at)}.` : "Pick a date and time."),
    interval: () => `Runs every ${sch.minutes} minutes while the app is open.`, daily: () => `Runs every day at ${sch.time}.`,
    weekly: () => (sch.days.length ? `Runs ${sch.days.map((d) => DAYS[d]).join(", ")} at ${sch.time}.` : "Pick at least one day.") };
  $("#tk-next").textContent = say[k]();
}
function formSchedule() {
  const k = $("#tk-sched").value, s = { kind: k };
  if (k === "once") s.at = $("#tk-at").value;
  if (k === "interval") s.minutes = +$("#tk-minutes").value || 60;
  if (k === "daily" || k === "weekly") s.time = $("#tk-time").value || "08:00";
  if (k === "weekly") s.days = $$("#tk-days .chip").filter((c) => c.getAttribute("aria-pressed") === "true").map((c) => +c.dataset.day);
  return s;
}
$("#tk-days").append(...DAYS.map((d, i) => el("button", { class: "chip", type: "button", "data-day": i, "aria-pressed": String(i < 5), text: d,
  onclick: (ev) => { const c = ev.currentTarget; c.setAttribute("aria-pressed", String(c.getAttribute("aria-pressed") !== "true")); renderSchedFields(); } })));
["#tk-sched", "#tk-at", "#tk-minutes", "#tk-time"].forEach((x) => $(x).addEventListener("input", renderSchedFields));
function renderTaskMembers(selected) {
  $("#tk-members").replaceChildren(...Object.values(S.personas).map((p) => el("button", { class: "chip", type: "button", "data-id": p.id,
    "aria-pressed": String(selected.includes(p.id)), text: p.name,
    onclick: (ev) => { const c = ev.currentTarget; c.setAttribute("aria-pressed", String(c.getAttribute("aria-pressed") !== "true")); } })));
}
function editTask(t) {
  t = t || { name: "", kind: "agent", prompt: "", persona: "", personas: Object.keys(S.personas).slice(0, 3), protocol: "roundtable",
    profile: "", permission: "safe", schedule: { kind: "manual" }, enabled: true };
  S.taskEdit = t.id || null;
  $("#task-heading").textContent = t.id ? `Edit “${t.name}”` : "New task";
  $("#tk-name").value = t.name; $("#tk-prompt").value = t.prompt || ""; setKind(t.kind);
  $("#tk-persona").value = t.persona || ""; $("#tk-profile").value = t.profile || ""; $("#tk-protocol").value = t.protocol || "roundtable";
  renderTaskMembers(t.personas || []);
  const s = t.schedule || { kind: "manual" };
  $("#tk-sched").value = s.kind; if (s.at) $("#tk-at").value = s.at.slice(0, 16);
  if (s.minutes) $("#tk-minutes").value = s.minutes; if (s.time) $("#tk-time").value = s.time;
  if (s.days) $$("#tk-days .chip").forEach((c) => c.setAttribute("aria-pressed", String(s.days.includes(+c.dataset.day))));
  $$("input[name=tk-perm]").forEach((r) => { r.checked = r.value === t.permission; });
  $("#tk-enabled").checked = t.enabled !== false;
  $("#tk-delete").disabled = !t.id;
  renderSchedFields(); renderTasks();
}
async function saveTask(runAfter) {
  const body = { id: S.taskEdit || undefined, name: $("#tk-name").value.trim(), kind: S.taskKind, prompt: $("#tk-prompt").value.trim(),
    persona: $("#tk-persona").value, profile: $("#tk-profile").value, protocol: $("#tk-protocol").value,
    personas: $$("#tk-members .chip").filter((c) => c.getAttribute("aria-pressed") === "true").map((c) => c.dataset.id),
    permission: $("input[name=tk-perm]:checked").value, schedule: formSchedule(), enabled: $("#tk-enabled").checked };
  try {
    const t = await api("POST", "/api/tasks", body);
    S.taskEdit = t.id;
    if (runAfter) await api("POST", "/api/tasks/run", { id: t.id });
    toast(runAfter ? `Saved and queued “${t.name}”.` : `Saved “${t.name}”.`);
    await loadTasks(); editTask(S.tasks.tasks.find((x) => x.id === t.id));
  } catch (e) { toast(e.message, 5000); }
}
$("#task-form").addEventListener("submit", (ev) => { ev.preventDefault(); saveTask(false); });
$("#tk-save-run").addEventListener("click", () => { if ($("#task-form").reportValidity()) saveTask(true); });
$("#t-new").addEventListener("click", () => { editTask(null); $("#tk-name").focus(); });
$("#tk-delete").addEventListener("click", async () => {
  if (!S.taskEdit || !confirm("Delete this task? (Its past results stay in the history.)")) return;
  try { await api("DELETE", `/api/tasks/${encodeURIComponent(S.taskEdit)}`); S.taskEdit = null; await loadTasks(); editTask(null); }
  catch (e) { toast(e.message); }
});

// ================================================================== CONTROL PANEL
const gb = (b) => (b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${Math.round(b / 1e6)} MB`);
async function loadControl() {
  try { S.control = await api("GET", "/api/control"); } catch (e) { return toast(e.message); }
  renderControl(); updateHealth();
}
function renderControl() {
  const c = S.control, rt = c.runtime, t = rt.task && rt.task.kind && !rt.task.finished ? rt.task : null;
  const state = !rt.installed ? ["Not installed", "concerned"] : rt.running ? ["Running", "happy"] : ["Stopped", "neutral"];
  $("#eng-state").textContent = t ? (t.kind === "install" ? "Installing…" : `Downloading ${t.name}…`) : state[0];
  const engFace = face(FACE_ENGINE, t ? "thinking" : state[1], "sm"); engFace.id = "eng-face"; $("#eng-face").replaceWith(engFace);
  $("#eng-detail").textContent = t ? `${t.status}${t.total ? ` · ${gb(t.done)} of ${gb(t.total)}` : ""}`
    : rt.running ? `Ollama ${rt.version || ""} at ${rt.url}${rt.bundled ? " · from your home folder" : rt.managed ? "" : " · installed on this computer"}${rt.loaded.length ? ` · loaded: ${rt.loaded.join(", ")}` : ""}`
      : rt.installed ? "Press Start (or let it start with the app)." : `Downloads Ollama (${rt.archive || "for this computer"}) into your home folder. Windows: about 1.6 GB.`;
  $("#eng-progress").classList.toggle("hidden", !t);
  if (t) $("#eng-progress div").style.width = `${t.total ? (100 * t.done) / t.total : 5}%`;
  $("#eng-install").classList.toggle("hidden", rt.installed || !!t);
  $("#eng-start").classList.toggle("hidden", !rt.installed || rt.running);
  $("#eng-stop").classList.toggle("hidden", !rt.running);
  $("#model-active").textContent = `in use: ${c.model}`;
  const have = new Set(rt.models.map((m) => m.name));
  $("#model-list").replaceChildren(...(rt.models.length ? rt.models.map((m) => {
    const active = m.name === c.model || m.name === `${c.model}:latest`;
    return el("div", { class: `model${active ? " active" : ""}` },
      el("div", {}, el("div", { class: "nm", text: m.name }), el("div", { class: "meta", text: `${gb(m.size)} · ${active ? "in use" : "installed"}` })),
      el("div", { class: "actions tight" },
        active ? el("span", { class: "pill", text: "✓ in use" }) : el("button", { class: "btn small", type: "button", text: "Use", onclick: () => modelAction("use", m.name) }),
        el("button", { class: "btn small ghost", type: "button", text: "Delete", onclick: () => confirm(`Delete ${m.name} (${gb(m.size)})?`) && modelAction("delete", m.name) })));
  }) : [el("p", { class: "hint", text: rt.running ? "No models yet - download one below." : "Start the engine to see your models." })]));
  $("#model-suggest").replaceChildren(...rt.suggested.filter(([n]) => !have.has(n)).map(([n, size, ram, , note]) => el("div", { class: "model" },
    el("div", {}, el("div", { class: "nm", text: n }), el("div", { class: "meta", text: `${size} download · needs ${ram} RAM · ${note}` })),
    el("button", { class: "btn small", type: "button", text: "Download", disabled: !rt.running || !!t, onclick: () => modelAction("pull", n) }))));
  const st = c.settings;
  $("#set-contact").value = c.contact; $("#set-searx").value = c.searxng;
  $("#set-sandbox").value = st.AGENT_SANDBOX || S.meta.sandbox || "auto"; $("#set-disk").value = st.AGENT_MIN_FREE_MB || 1024;
  $("#set-safe").checked = ["1", "true", "yes", "on"].includes(String(st.AGENT_SAFE_MODE || S.meta.safe_mode).toLowerCase());
  $("#set-autostart").checked = !["0", "false", "no", "off"].includes(String(st.AGENT_AUTO_START_MODEL || "1").toLowerCase());
  const kv = [["Home folder", c.home || "(developer mode: settings come from .env)"], ["Model engine", gb(c.disk.engine_bytes)],
    ["Models", gb(c.disk.models_bytes)], ["Free disk", `${c.free_gb} GB`]];
  $("#storage").replaceChildren(...kv.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));
}
async function modelAction(action, name) {
  try { S.control = await api("POST", "/api/models", { action, name }); renderControl(); updateHealth();
    if (action === "use") { toast(`Agents now use ${name}.`); S.meta = await api("GET", "/api/meta"); } }
  catch (e) { toast(e.message, 5000); }
}
async function engine(action) {
  try { const r = await api("POST", "/api/runtime", { action }); toast(`Engine: ${r.result}`); loadControl(); }
  catch (e) { toast(e.message, 6000); }
}
$("#eng-install").addEventListener("click", () => confirm("Download the Ollama model engine from ollama.com into your home folder? (about 1.6 GB on Windows)") && engine("install"));
$("#eng-start").addEventListener("click", () => engine("start"));
$("#eng-stop").addEventListener("click", () => engine("stop"));
$("#model-pull").addEventListener("click", () => { const n = $("#model-name").value.trim(); if (n) modelAction("pull", n); });
$("#online-run").addEventListener("click", async () => {
  const box = $("#online-list"); box.replaceChildren(el("p", { class: "hint", text: "Checking… (a few seconds)" }));
  $("#online-run").disabled = true;
  try {
    const rows = await api("GET", "/api/online");
    box.replaceChildren(...rows.map((r) => el("div", { class: "check-row" }, el("span", { class: r.ok ? "ok" : "no", text: r.ok ? "✓" : "✕" }),
      el("span", { text: r.check }), el("span", { class: "d", text: r.detail, title: r.detail }), el("span", { class: "hint", text: `${r.ms} ms` }))));
    const okN = rows.filter((r) => r.ok).length;
    toast(okN === rows.length ? "Online: every check passed." : `${okN}/${rows.length} online checks passed - see the details.`);
  } catch (e) { box.replaceChildren(el("p", { class: "hint", text: e.message })); }
  $("#online-run").disabled = false;
});
$("#settings-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const changes = { AGENT_CONTACT: $("#set-contact").value.trim(), SEARXNG_URL: $("#set-searx").value.trim(),
    AGENT_SANDBOX: $("#set-sandbox").value, AGENT_MIN_FREE_MB: String(+$("#set-disk").value || 1024),
    AGENT_SAFE_MODE: $("#set-safe").checked ? "1" : "0", AGENT_AUTO_START_MODEL: $("#set-autostart").checked ? "1" : "0" };
  try { S.control = await api("POST", "/api/settings", { changes }); renderControl(); toast("Settings saved."); loadSafety(); }
  catch (e) { toast(e.message, 5000); }
});
$("#quit").addEventListener("click", async () => {
  if (!confirm("Quit Hybrid Agent? This stops the GUI, the task scheduler and the model engine.")) return;
  try { await api("POST", "/api/quit", {}); } catch { /* the server is going away */ }
  document.body.replaceChildren(el("main", {}, el("div", { class: "empty", style: "margin-top:20vh" }, "Hybrid Agent has stopped.", el("br"),
    "Start it again from HybridAgent.exe (or hybrid-agent studio).")));
});
// One "is everything OK?" signal for the top bar (research: lead with the answer, details on demand).
function updateHealth() {
  const c = S.control, h = $("#health");
  let level = "ok", text = "Ready";
  if (S.meta && /scripted/.test(S.meta.backend)) { level = "warn"; text = "Demo mode (scripted replies)"; }
  else if (c && c.backend_mode !== "claude") {
    const rt = c.runtime, have = rt.models.some((m) => m.name === c.model || m.name === `${c.model}:latest`);
    if (!rt.running) { level = "bad"; text = rt.installed ? "Model engine stopped" : "No model engine yet"; }
    else if (!have) { level = "warn"; text = `Model ${c.model} not downloaded`; }
    else text = `Ready · ${c.model}`;
  }
  if (level === "ok" && S.safetyLevel === "bad") { level = "warn"; text += " · check Safety"; }
  h.className = `health ${level}`; $("#health-text").textContent = text;
  $("#banner").classList.toggle("hidden", level !== "bad" || S.bannerDismissed);
  $("#banner-text").textContent = text + ".";
}
$("#health").addEventListener("click", () => showTab("control"));
$("#banner-go").addEventListener("click", () => { showTab("control"); $("#banner").classList.add("hidden"); });

// ================================================================== APPROVAL / QUESTION DIALOG
const VERBS = { run_shell: ["run a command", "command"], run_python: ["run Python code", "code"], run_tests: ["run tests", "path"],
  delete_path: ["delete (moved to the undo history)", "path"], move_path: ["move a file", "source"], download_file: ["download a file", "url"],
  git_commit: ["make a git commit", "message"], restore_backup: ["restore a backup", "backup_id"] };
let modalTimer;
function openModal(e) {
  S.modalId = e.request_id;
  const isQ = e.type === "question", who = nameOf(e.agent);
  const risk = isQ ? "question" : (e.reason || "").split(" ")[0];
  const [verb, key] = VERBS[e.tool] || [`use ${e.tool}`, Object.keys(e.args || {})[0]];
  $("#m-risk").className = `risk ${risk}`; $("#m-risk").textContent = isQ ? "question" : `${risk} action`;
  $("#m-title").textContent = isQ ? `${who} asks:` : `Allow ${who} to ${verb}?`;
  $("#m-text").textContent = isQ ? e.question : "Check this before allowing. If you're not sure, Deny - the agent will work around it.";
  $("#m-main").textContent = isQ ? "" : String(e.args?.[key] ?? "");
  $("#m-pre").textContent = isQ ? "" : JSON.stringify(e.args, null, 2);
  $("#m-details").classList.toggle("hidden", isQ);
  $("#m-input").classList.toggle("hidden", !isQ); $("#m-input").value = "";
  $("#m-yes").textContent = isQ ? "Send answer" : "Allow once"; $("#m-no").textContent = isQ ? "Skip" : "Deny";
  $("#modal").dataset.kind = e.type;
  $("#modal").classList.remove("hidden");
  (isQ ? $("#m-input") : $("#m-no")).focus();     // safe default focus: Deny
  const total = Math.round(e.timeout); let left = total;
  const tick = () => {
    $("#m-timer").textContent = `No answer in ${left}s = ${isQ ? "skipped" : "denied"}`;
    $("#m-bar").style.width = `${(100 * left) / total}%`;
  };
  tick(); clearInterval(modalTimer);
  modalTimer = setInterval(() => { left -= 1; tick(); if (left <= 0) closeModal(); }, 1000);
}
function closeModal() { clearInterval(modalTimer); $("#modal").classList.add("hidden"); S.modalId = null; }
async function answerModal(yes) {
  const id = S.modalId; if (!id) return;
  const isQ = $("#modal").dataset.kind === "question", text = $("#m-input").value;
  closeModal();
  try {
    if (isQ) await api("POST", "/api/answer", { request_id: id, text: yes ? text : "" });
    else await api("POST", "/api/approve", { request_id: id, allow: yes });
  } catch (err) { toast(err.message); }
}
$("#m-yes").addEventListener("click", () => answerModal(true));
$("#m-no").addEventListener("click", () => answerModal(false));
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && S.modalId) answerModal(false); });

// ================================================================== EVENTS (live feed)
function onEvent(e) {
  switch (e.type) {
    case "job_start": setBusy({ id: e.job_id, kind: e.kind }); break;
    case "job_done":
      setBusy(null);
      if (e.kind === "council") onCouncilDone(e.result);
      if (e.kind === "chat") endTurn(e.result.answer);
      if (e.kind === "diagnose") renderDrills(e.result);
      if (e.kind === "task") { S.runningTask = ""; toast(`Task “${e.result.name}” finished.`); loadTasks(); }
      break;
    case "job_error":
      setBusy(null); toast(e.error, 6000);
      if (e.kind === "chat") endTurn(`Error: ${e.error}`, true);
      if (e.kind === "council") feedSys(`Error: ${e.error}`, true);
      if (e.kind === "task") { S.runningTask = ""; loadTasks(); }
      break;
    case "job_cancelled":
      setBusy(null); toast("Stopped.");
      if (e.kind === "chat") endTurn("(stopped)", true);
      if (e.kind === "task") { S.runningTask = ""; loadTasks(); }
      if (e.kind === "council") { feedSys("Stopped."); for (const x of Object.values(S.stage)) setExpr(x.pre, "neutral"); }
      break;
    case "council_setup": buildStage(e.members, e.chair, e.question); break;
    case "council": onCouncilEvent(e); break;
    case "tool_call": if (S.stage[e.agent]) S.stage[e.agent].state.textContent = `using ${e.name}…`; break;
    case "agent": if (e.kind === "tool_call" || e.kind === "tool_result") turnTool(e.kind, e.data); break;
    case "approval_request": case "question": openModal(e); break;
    case "request_expired": if (S.modalId === e.request_id) closeModal(); break;
    case "restored": if ($("#tab-safety").classList.contains("active")) loadSafety(); break;
    case "tasks_changed": loadTasks(); break;
    case "task_started": S.runningTask = e.task; renderTasks(); break;
    case "runtime_progress":
      if (S.control) { S.control.runtime.task = e; renderControl(); }
      if (e.finished) { toast(e.error ? `${e.kind} failed: ${e.status}` : `${e.kind === "install" ? "Engine installed" : `${e.name} downloaded`}.`, 5000); loadControl(); }
      break;
  }
}
function connectEvents() {
  const es = new EventSource(`/api/events?token=${encodeURIComponent(TOKEN)}`);
  es.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (err) { console.warn(err); } };
  es.onerror = () => { $("#health").className = "health warn"; $("#health-text").textContent = "reconnecting…"; };
  es.onopen = () => { if (S.control) updateHealth(); };
}

// ================================================================== BOOT
async function loadPersonas() {
  const list = await api("GET", "/api/personas");
  S.personas = Object.fromEntries(list.map((p) => [p.id, p]));
  S.picked = S.picked.filter((id) => S.personas[id]);
  if (!S.picked.length) S.picked = list.slice(0, 3).map((p) => p.id);
  renderPicker(); renderPersonaList();
  const cp = $("#chat-persona"), cur = cp.value;
  cp.replaceChildren(el("option", { value: "", text: "Agent (no persona)" }),
    ...list.map((p) => el("option", { value: p.id, text: `${p.name} — ${p.title}` })));
  cp.value = S.personas[cur] ? cur : ""; S.chatPersona = cp.value; chatHeader();
  $("#tk-persona").replaceChildren(el("option", { value: "", text: "no persona" }), ...list.map((p) => el("option", { value: p.id, text: p.name })));
  editPersona(S.editing && S.personas[S.editing] ? S.editing : list[0]?.id);
}
$("#banner-close").addEventListener("click", () => { S.bannerDismissed = true; $("#banner").classList.add("hidden"); });

async function boot() {
  if (!TOKEN) { document.body.textContent = "Open the link with ?token= printed in the terminal."; return; }
  $("#guide-link").href = `/guide?token=${encodeURIComponent(TOKEN)}`;
  try { S.meta = await api("GET", "/api/meta"); } catch (e) { $("#health-text").textContent = e.message; return; }
  $("#health").title = `Model: ${S.meta.backend} · workspace: ${S.meta.workspace} · click for the Control panel`;
  const opts = (xs) => xs.map((x) => el("option", { value: x, text: x }));
  $("#p-role").replaceChildren(...Object.entries(S.meta.roles).map(([k, r]) => el("option", { value: k, text: r.title })));
  $("#chat-profile").replaceChildren(el("option", { value: "", text: "automatic" }), ...opts(S.meta.profiles));
  $("#p-tools").replaceChildren(el("option", { value: "", text: "role default" }), ...opts(S.meta.profiles));
  $("#tk-profile").replaceChildren(el("option", { value: "", text: "automatic" }), ...opts(S.meta.profiles));
  $("#tk-protocol").replaceChildren(...Object.keys(S.meta.protocols).map((k) => el("option", { value: k, text: PROTOCOLS[k]?.[0] || k })));
  $("#t-profile").append(...opts(S.meta.profiles));
  for (const k of PARTS) $(`#f-${k}`).replaceChildren(...opts(S.meta.face_parts[k]));
  $("#p-expr").replaceChildren(...S.meta.expressions.map((ex) => el("button", { class: "chip", type: "button", text: ex,
    onclick: () => { S.editorExpr = ex; updatePreview(); } })));
  renderProtocols();
  S.tools = await api("GET", "/api/tools");
  await loadPersonas();
  renderToolFilters(); renderTools();
  if (S.meta.busy) setBusy(S.meta.busy);
  if (S.meta.auto_approve) toast("Auto-approve is ON (-y): risky tools will run without asking.", 6000);
  try { const t = sessionStorage.getItem("tab"); if (t) showTab(t); } catch { /* ignore */ }
  connectEvents();
  loadSafety(); loadControl(); loadTasks().then(() => editTask(null));
}
boot();
