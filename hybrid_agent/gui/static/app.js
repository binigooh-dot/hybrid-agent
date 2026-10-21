// [GUI / app] Agent Studio front-end. Plain JavaScript, no libraries, works offline.
// Security rule: anything written by a model is shown with textContent, never innerHTML.
// The only innerHTML used is for persona faces, which are SVG generated (and sanitised) by the server.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const TOKEN = new URLSearchParams(location.search).get("token") || "";
const S = { meta: null, personas: {}, tools: [], picked: new Set(), job: null, stage: {}, chatPersona: "",
            modalId: null, editing: null, editorExpr: "neutral" };

// ------------------------------------------------------------------ helpers
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
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
const fmtTime = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

// ------------------------------------------------------------------ faces
function faceSvg(pid, expr) {
  const p = S.personas[pid];
  return p ? (p.faces[expr] || p.faces.neutral) : "";
}
function idleExpr(pid) {
  const p = S.personas[pid];
  return p && p.role === "skeptic" ? "skeptical" : "neutral";
}
function setFace(box, pid, expr, mode = "") {
  if (!box) return;
  const p = S.personas[pid];
  if (p && p.image) {             // a picture instead of the drawn face (groundwork for portraits/avatars)
    if (!box.querySelector("img")) box.replaceChildren(el("img", { src: imageUrl(p.image), alt: p.name }));
  } else {
    box.innerHTML = faceSvg(pid, expr);   // server-generated, sanitised SVG
  }
  box.classList.remove("speaking", "thinking");
  if (mode) box.classList.add(mode);
}
function imageUrl(img) {
  return img.startsWith("https://") ? img : `/persona-image/${encodeURIComponent(img)}?token=${TOKEN}`;
}

// ------------------------------------------------------------------ tabs + theme
function showTab(name) {
  $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  $$(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${name}`));
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

// ------------------------------------------------------------------ busy state
function setBusy(job) {
  S.job = job;
  $("#busy").classList.toggle("hidden", !job);
  if (job) $("#busy-label").textContent = `Running ${job.kind}…`;
  for (const b of ["#c-run", "#s-run"]) $(b).disabled = !!job;
  $("#chat-form button").disabled = !!job;
}
$("#stop").addEventListener("click", async () => {
  try { await api("POST", "/api/stop", {}); toast("Stopping at the next safe point…"); } catch (e) { toast(e.message); }
});

// ================================================================== COUNCIL
const CALLS = { roundtable: (n) => n + 1, debate: (n, r) => n * r + 1, vote: (n) => n + 2, critique: (n, r) => 1 + r * Math.max(n - 1, 0) + r };
function councilEstimate() {
  const n = Math.max(S.picked.size - 1, 1), r = +$("#c-rounds").value || 1, proto = $("#c-protocol").value;
  const calls = (CALLS[proto] || CALLS.roundtable)(n, r);
  $("#c-estimate").textContent = S.picked.size
    ? `≈ ${calls} model contributions (each may use several tool steps).` : "";
}
function renderPicker() {
  const box = $("#c-personas"); box.replaceChildren();
  for (const p of Object.values(S.personas)) {
    const b = el("button", { class: "pick", type: "button", "aria-pressed": String(S.picked.has(p.id)), title: p.personality },
      el("div", { class: "face-mini" }), el("div", { class: "nm", text: p.name }), el("div", { class: "rl", text: p.title }));
    setFace(b.querySelector(".face-mini"), p.id, "neutral");
    b.addEventListener("click", () => {
      S.picked.has(p.id) ? S.picked.delete(p.id) : S.picked.add(p.id);
      b.setAttribute("aria-pressed", String(S.picked.has(p.id))); renderChair(); councilEstimate();
    });
    box.append(b);
  }
  renderChair(); councilEstimate();
}
function renderChair() {
  const sel = $("#c-chair"), prev = sel.value; sel.replaceChildren(el("option", { value: "", text: "automatic (role 'chair', else first)" }));
  for (const id of S.picked) sel.append(el("option", { value: id, text: S.personas[id].name }));
  if ([...S.picked].includes(prev)) sel.value = prev;
}
$("#c-protocol").addEventListener("change", () => {
  $("#c-protocol-desc").textContent = S.meta.protocols[$("#c-protocol").value] || ""; councilEstimate();
});
$("#c-rounds").addEventListener("input", councilEstimate);
$("#c-run").addEventListener("click", async () => {
  const question = $("#c-question").value.trim();
  if (!question) return toast("Write a question first.");
  if (!S.picked.size) return toast("Pick at least one member.");
  const options = $("#c-options").value.split(",").map((s) => s.trim()).filter(Boolean);
  try {
    await api("POST", "/api/council", { question, personas: [...S.picked], chair: $("#c-chair").value,
      protocol: $("#c-protocol").value, rounds: +$("#c-rounds").value || 2, options });
  } catch (e) { toast(e.message); }
});

function buildStage(members, chair) {
  const stage = $("#stage"); stage.replaceChildren(); S.stage = {};
  $("#c-final").classList.add("hidden"); $("#c-log").replaceChildren();
  for (const id of members) {
    const p = S.personas[id] || { name: id, title: "" };
    const card = el("div", { class: "member", id: `m-${id}` },
      id === chair ? el("span", { class: "chair-badge", text: "chair" }) : null,
      el("div", { class: "face" }), el("div", { class: "name", text: p.name }), el("div", { class: "title", text: p.title }),
      el("div", { class: "state", text: "waiting" }), el("div", { class: "vote" }), el("div", { class: "bubble" }));
    stage.append(card);
    S.stage[id] = { card, face: card.querySelector(".face"), state: card.querySelector(".state"),
                    bubble: card.querySelector(".bubble"), vote: card.querySelector(".vote"), last: "" };
    setFace(S.stage[id].face, id, idleExpr(id));
    if (p.greeting) S.stage[id].bubble.textContent = p.greeting;
  }
}
function logLine(text, cls = "") {
  const li = el("li", { class: cls }, el("span", { class: "t", text: new Date().toLocaleTimeString() }), text);
  const log = $("#c-log"); log.append(li); log.scrollTop = log.scrollHeight;
}
function voteOf(text) {
  const m = [...(text || "").matchAll(/^\W*VOTE\W*:\s*(.+?)\s*$/gim)];
  return m.length ? m[m.length - 1][1].replace(/[*`]/g, "").trim() : "";
}
function onCouncilEvent(e) {
  const m = S.stage[e.member];
  switch (e.event) {
    case "round_start": logLine(`Round ${e.round}: ${e.kind} (${e.members.join(", ")})`); break;
    case "member_start":
      if (!m) break;
      m.card.classList.add("active"); m.state.textContent = `thinking (${e.kind})…`;
      setFace(m.face, e.member, "thinking", "thinking"); break;
    case "member_done":
      if (!m) break;
      m.card.classList.remove("active");
      if (e.error) {
        m.card.classList.add("error"); m.state.textContent = "unavailable"; setFace(m.face, e.member, "concerned");
        logLine(`${e.member}: ${e.error}`, "err"); break;
      }
      m.last = e.content || e.preview || ""; m.bubble.textContent = m.last;
      const v = voteOf(m.last); m.vote.textContent = v ? `votes: ${v}` : "";
      m.state.textContent = `${e.kind} · ${e.seconds.toFixed(1)}s`;
      setFace(m.face, e.member, "speaking", "speaking");
      clearTimeout(m.timer); m.timer = setTimeout(() => setFace(m.face, e.member, idleExpr(e.member)), 2600);
      logLine(`${S.personas[e.member]?.name || e.member} — ${e.kind}`); break;
    case "consensus":
      logLine(`Consensus reached on “${e.winner}” — stopping early.`);
      for (const [id, x] of Object.entries(S.stage)) setFace(x.face, id, "happy"); break;
    case "options": logLine(`Options proposed: ${e.options.join(" | ")}`); break;
    case "chair_failed": logLine("The chair could not answer; showing members' positions.", "err"); break;
  }
}
function onCouncilDone(res) {
  const box = $("#c-final"); box.classList.remove("hidden"); box.replaceChildren(el("h2", { text: "Council answer" }));
  const winner = res.tally?.winner;
  if (res.tally) {
    box.append(el("div", { class: "muted", text: `Vote: ${res.tally.summary}` }));
    const bars = el("div", { class: "bars" }), max = Math.max(...Object.values(res.tally.scores), 0.0001);
    for (const [opt, sc] of Object.entries(res.tally.scores).sort((a, b) => b[1] - a[1])) {
      const fill = el("div", { class: "fill" }); fill.style.width = `${(100 * sc) / max}%`;
      bars.append(el("div", { class: "bar" }, el("span", { text: opt }), el("div", { class: "track" }, fill), el("span", { text: sc.toFixed(2) })));
    }
    box.append(bars);
  }
  box.append(el("div", { class: "answer", text: res.final_answer }),
    el("p", { class: "muted mono", text: `${res.seconds.toFixed(1)}s · transcript: ${res.transcript}` }));
  for (const [id, x] of Object.entries(S.stage)) {
    const v = voteOf(x.last);
    const expr = !winner || !v ? "happy" : v.toLowerCase().startsWith(winner.toLowerCase()) ? "happy" : "concerned";
    setFace(x.face, id, x.card.classList.contains("error") ? "concerned" : expr);
  }
  logLine("Deliberation finished.");
}

// ================================================================== CHAT
function chatAvatar(pid, expr = "neutral") {
  const box = el("div", { class: "av" });
  if (pid) setFace(box, pid, expr); else box.textContent = "🤖";
  return box;
}
function chatMsg(who, text) {
  const pid = who === "agent" ? S.chatPersona : "";
  const row = el("div", { class: `msg ${who}` }, who === "agent" ? chatAvatar(pid, "speaking") : el("div", { class: "av", text: "🙂" }),
    el("div", { class: "txt", text }));
  $("#chat-log").append(row); $("#chat-log").scrollTop = 1e9; return row;
}
function chatActivity(text, err = false) {
  const line = el("div", { class: `activity${err ? " err" : ""}`, text });
  $("#chat-log").append(line); $("#chat-log").scrollTop = 1e9; return line;
}
$("#chat-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const text = $("#chat-input").value.trim(); if (!text) return;
  chatMsg("user", text); $("#chat-input").value = "";
  try {
    await api("POST", "/api/chat", { message: text, persona: S.chatPersona, profile: $("#chat-profile").value });
    chatActivity("thinking…").classList.add("pending");
  } catch (e) { chatActivity(e.message, true); }
});
$("#chat-input").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); $("#chat-form").requestSubmit(); }
});
$("#chat-persona").addEventListener("change", () => { S.chatPersona = $("#chat-persona").value; greet(); });
$("#chat-reset").addEventListener("click", async () => {
  await api("POST", "/api/chat/reset", {}).catch((e) => toast(e.message)); $("#chat-log").replaceChildren(); greet();
});
function greet() {
  const p = S.personas[S.chatPersona];
  if (p && p.greeting) chatMsg("agent", p.greeting);
}

// ================================================================== PERSONAS
const FACE_KEYS = ["skin", "hair", "eyes", "accent", "background", "shape", "hair_style", "mouth_style",
                   "glasses", "beard", "earrings", "freckles", "blush"];
function renderPersonaList() {
  const box = $("#p-list"); box.replaceChildren();
  for (const p of Object.values(S.personas)) {
    const c = el("div", { class: `pcard${S.editing === p.id ? " sel" : ""}`, tabindex: "0", role: "button" },
      el("div", { class: "fc" }), el("div", { text: p.name, style: "font-weight:600" }),
      el("div", { class: "muted", text: `${p.title}${p.builtin ? " · built-in" : ""}`, style: "font-size:12px" }));
    setFace(c.querySelector(".fc"), p.id, "happy");
    c.addEventListener("click", () => editPersona(p.id));
    c.addEventListener("keydown", (ev) => { if (ev.key === "Enter") editPersona(p.id); });
    box.append(c);
  }
}
function editPersona(id, copyFrom) {
  const p = copyFrom || S.personas[id] || { id: "", name: "", role: "generalist", face: {} };
  S.editing = copyFrom ? null : id;
  $("#p-heading").textContent = copyFrom ? "New persona" : `Edit ${p.name}`;
  const v = (sel, val) => { $(sel).value = val ?? ""; };
  v("#p-id", copyFrom ? "" : p.id); v("#p-name", p.name); v("#p-role", p.role); v("#p-title", p.title);
  v("#p-personality", p.personality); v("#p-style", p.speaking_style); v("#p-greeting", p.greeting);
  v("#p-backend", p.backend || "default"); v("#p-weight", p.weight || 1); v("#p-tools", p.tools || "");
  const f = p.face || {};
  for (const k of FACE_KEYS) {
    const input = $(`#f-${k}`);
    if (input.type === "checkbox") input.checked = !!f[k]; else if (f[k] != null) input.value = f[k];
  }
  $("#p-del").disabled = copyFrom || !S.personas[id] || S.personas[id].builtin;
  renderPersonaList(); updatePreview();
}
function formFace() {
  const f = {};
  for (const k of FACE_KEYS) { const i = $(`#f-${k}`); f[k] = i.type === "checkbox" ? i.checked : i.value; }
  return f;
}
let previewTimer;
function updatePreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    try {
      const r = await api("POST", "/api/face", { face: formFace(), expression: S.editorExpr });
      $("#p-preview").innerHTML = r.svg;   // server-generated, sanitised SVG
    } catch (e) { toast(e.message); }
  }, 120);
}
$$("#p-form [id^=f-]").forEach((i) => i.addEventListener("input", updatePreview));
$("#p-random").addEventListener("click", async () => {
  const { face } = await api("GET", `/api/face/random?seed=${Math.random().toString(36).slice(2)}`);
  for (const k of FACE_KEYS) { const i = $(`#f-${k}`); if (i.type === "checkbox") i.checked = !!face[k]; else i.value = face[k]; }
  updatePreview();
});
$("#p-new").addEventListener("click", () => editPersona(null, { name: "", role: "generalist", face: {} }));
$("#p-dup").addEventListener("click", () => {
  const cur = S.personas[S.editing]; if (!cur) return toast("Select a persona to duplicate.");
  editPersona(null, { ...cur, name: `${cur.name} 2` });
});
$("#p-del").addEventListener("click", async () => {
  if (!S.editing || !confirm(`Delete your persona file for “${S.editing}”?`)) return;
  try { await api("DELETE", `/api/personas/${encodeURIComponent(S.editing)}`); toast("Deleted."); await loadPersonas(); }
  catch (e) { toast(e.message); }
});
$("#p-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const body = { id: $("#p-id").value.trim().toLowerCase(), name: $("#p-name").value.trim(), role: $("#p-role").value,
    title: $("#p-title").value.trim(), personality: $("#p-personality").value.trim(), speaking_style: $("#p-style").value.trim(),
    greeting: $("#p-greeting").value.trim(), backend: $("#p-backend").value.trim() || "default",
    tools: $("#p-tools").value || null, weight: +$("#p-weight").value || 1, face: formFace(),
    image: S.personas[S.editing]?.image || null };
  try { await api("POST", "/api/personas", body); toast(`Saved ${body.name}.`); S.editing = body.id; await loadPersonas(); }
  catch (e) { toast(e.message, 5000); }
});

// ================================================================== TOOLS
let toolCat = "";
function renderTools() {
  const q = $("#t-search").value.toLowerCase(), risk = $("#t-risk").value, prof = $("#t-profile").value;
  const grid = $("#t-grid"); grid.replaceChildren(); let n = 0;
  for (const t of S.tools) {
    if (toolCat && t.category !== toolCat) continue;
    if (risk && t.risk !== risk) continue;
    if (prof && !(S.profileTools[prof] || []).includes(t.name)) continue;
    if (q && !(t.name + t.description + t.category).toLowerCase().includes(q)) continue;
    n++;
    const args = Object.entries(t.parameters.properties || {}).map(([k, v]) =>
      `${k}${(t.parameters.required || []).includes(k) ? "" : "?"}: ${v.type || "any"}`).join(", ");
    grid.append(el("div", { class: "tcard" }, el("h3", { text: t.name }),
      el("span", { class: `tag ${t.risk}`, text: t.risk }), " ", el("span", { class: "tag", text: t.category }),
      t.approval ? el("span", { class: "tag", text: "asks approval" }) : null,
      el("p", { text: t.description }), el("div", { class: "args", text: args ? `(${args})` : "(no arguments)" })));
  }
  $("#t-count").textContent = `${n} of ${S.tools.length} tools`;
}
function renderToolFilters() {
  const cats = [...new Set(S.tools.map((t) => t.category))].sort();
  const box = $("#t-cats"); box.replaceChildren();
  for (const c of ["", ...cats]) {
    const b = el("button", { class: "chip", type: "button", "aria-pressed": String(c === toolCat), text: c || "all" });
    b.addEventListener("click", () => { toolCat = c; renderToolFilters(); renderTools(); });
    box.append(b);
  }
}
["#t-search", "#t-risk", "#t-profile"].forEach((s) => $(s).addEventListener("input", renderTools));

// ================================================================== SAFETY
$("#s-run").addEventListener("click", async () => {
  try { await api("POST", "/api/diagnose", {}); $("#s-summary").textContent = "Running drills… (about a minute)"; }
  catch (e) { toast(e.message); }
});
$("#s-doctor").addEventListener("click", async () => {
  try {
    const rows = await api("GET", "/api/doctor");
    const fails = rows.filter((r) => r.required && r.status === "FAIL").length;
    $("#s-summary").textContent = fails ? `Setup: ${fails} required item(s) missing` : "Setup: ready to run without an API key";
    const t = $("#s-table"); t.replaceChildren(el("tr", {}, el("th", { text: "" }), el("th", { text: "Check" }), el("th", { text: "Detail" })));
    for (const r of rows) t.append(el("tr", {}, el("td", { class: r.status === "PASS" ? "pass" : r.status === "FAIL" ? "fail" : "", text: r.status }),
      el("td", { text: `${r.check}${r.required ? "" : " (optional)"}` }), el("td", { text: r.detail })));
  } catch (e) { toast(e.message); }
});
function renderDrills(rep) {
  $("#s-summary").textContent = `${rep.passed}/${rep.total} drills passed` +
    (rep.critical_failures.length ? ` — CRITICAL: ${rep.critical_failures.join(", ")}` : " — no critical failures");
  const t = $("#s-table");
  t.replaceChildren(el("tr", {}, el("th", { text: "" }), el("th", { text: "Drill" }), el("th", { text: "Severity" }), el("th", { text: "Result" })));
  for (const d of rep.drills) {
    t.append(el("tr", { title: d.scenario }, el("td", { class: d.passed ? "pass" : "fail", text: d.passed ? "PASS" : "FAIL" }),
      el("td", {}, el("div", { text: d.title }), el("div", { class: "muted", style: "font-size:12px", text: d.scenario })),
      el("td", { text: d.severity }), el("td", { text: d.detail })));
  }
  for (const c of rep.integrity) {
    t.append(el("tr", {}, el("td", { class: c.passed ? "pass" : "fail", text: c.passed ? "PASS" : "FAIL" }),
      el("td", { text: `integrity: ${c.name}` }), el("td", { text: "" }), el("td", { text: c.detail })));
  }
}

// ================================================================== MODAL (approvals + questions)
let modalTimer;
function openModal(e) {
  S.modalId = e.request_id;
  const isQ = e.type === "question";
  $("#m-title").textContent = isQ ? `${e.agent} asks` : `Allow ${e.tool}?`;
  $("#m-text").textContent = isQ ? e.question
    : `${S.personas[e.agent]?.name || e.agent} wants to use ${e.tool} (${e.reason.replace(/^(\w+) tool$/, "$1-level tool")}). Check the details:`;
  $("#m-pre").textContent = isQ ? "" : JSON.stringify(e.args, null, 2);
  $("#m-pre").classList.toggle("hidden", isQ);
  $("#m-input").classList.toggle("hidden", !isQ); $("#m-input").value = "";
  $("#m-yes").textContent = isQ ? "Send answer" : "Allow"; $("#m-no").textContent = isQ ? "Skip" : "Deny";
  $("#modal").classList.remove("hidden");
  (isQ ? $("#m-input") : $("#m-no")).focus();     // safe default focus: Deny
  let left = Math.round(e.timeout);
  $("#m-timer").textContent = `Automatically ${isQ ? "skipped" : "denied"} in ${left}s`;
  clearInterval(modalTimer);
  modalTimer = setInterval(() => {
    left -= 1; $("#m-timer").textContent = `Automatically ${isQ ? "skipped" : "denied"} in ${left}s`;
    if (left <= 0) closeModal();
  }, 1000);
  $("#modal").dataset.kind = e.type;
}
function closeModal() { clearInterval(modalTimer); $("#modal").classList.add("hidden"); S.modalId = null; }
async function answerModal(yes) {
  const id = S.modalId; if (!id) return;
  const isQ = $("#modal").dataset.kind === "question";
  closeModal();
  try {
    if (isQ) await api("POST", "/api/answer", { request_id: id, text: yes ? $("#m-input").value : "" });
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
      if (e.kind === "chat") { $$(".activity.pending").forEach((x) => x.remove()); chatMsg("agent", e.result.answer); }
      if (e.kind === "diagnose") renderDrills(e.result);
      break;
    case "job_error":
      setBusy(null); toast(e.error, 6000);
      if (e.kind === "chat") chatActivity(`error: ${e.error}`, true);
      if (e.kind === "council") logLine(`error: ${e.error}`, "err");
      break;
    case "job_cancelled": setBusy(null); toast("Stopped."); break;
    case "council_setup": buildStage(e.members, e.chair); logLine(`Council convened (${e.protocol}): ${e.question}`); break;
    case "council": onCouncilEvent(e); break;
    case "tool_call":
      if (S.stage[e.agent]) logLine(`${e.agent} → ${e.name}(${JSON.stringify(e.arguments).slice(0, 120)})`);
      break;
    case "agent":
      if (e.kind === "tool_call") chatActivity(`→ ${e.data.name}(${JSON.stringify(e.data.arguments).slice(0, 160)})`);
      else if (e.kind === "tool_result") chatActivity(`  ${(e.data.preview || "").split("\n")[0].slice(0, 160)}`, e.data.is_error);
      else if (e.kind === "thought") chatActivity(e.data.text.slice(0, 300));
      break;
    case "approval_request": case "question": openModal(e); break;
    case "request_expired": if (S.modalId === e.request_id) closeModal(); break;
  }
}
function connectEvents() {
  const es = new EventSource(`/api/events?token=${encodeURIComponent(TOKEN)}`);
  es.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (err) { console.warn(err); } };
  es.onerror = () => { $("#status").textContent = "reconnecting…"; };
  es.onopen = () => { if (S.meta) $("#status").textContent = S.meta.backend; };
}

// ================================================================== BOOT
async function loadPersonas() {
  const list = await api("GET", "/api/personas");
  S.personas = Object.fromEntries(list.map((p) => [p.id, p]));
  if (!S.picked.size) for (const p of list.slice(0, 3)) S.picked.add(p.id);
  for (const id of [...S.picked]) if (!S.personas[id]) S.picked.delete(id);
  renderPicker(); renderPersonaList();
  const cp = $("#chat-persona"), cur = cp.value;
  cp.replaceChildren(el("option", { value: "", text: "Agent (no persona)" }),
    ...list.map((p) => el("option", { value: p.id, text: `${p.name} — ${p.title}` })));
  cp.value = S.personas[cur] ? cur : "";
  if (S.editing && S.personas[S.editing]) editPersona(S.editing); else if (list.length && !S.editing) editPersona(list[0].id);
}
async function boot() {
  if (!TOKEN) { document.body.textContent = "Open the link with ?token= printed in the terminal."; return; }
  $("#guide-link").href = `/guide?token=${encodeURIComponent(TOKEN)}`;
  try {
    S.meta = await api("GET", "/api/meta");
  } catch (e) { $("#status").textContent = e.message; return; }
  $("#status").textContent = S.meta.backend; $("#status").title = `Workspace: ${S.meta.workspace}`;
  $("#c-protocol").replaceChildren(...Object.keys(S.meta.protocols).map((k) => el("option", { value: k, text: k })));
  $("#c-protocol-desc").textContent = S.meta.protocols[$("#c-protocol").value];
  $("#p-role").replaceChildren(...Object.entries(S.meta.roles).map(([k, r]) => el("option", { value: k, text: r.title })));
  const profOpts = () => S.meta.profiles.map((p) => el("option", { value: p, text: p }));
  $("#chat-profile").replaceChildren(el("option", { value: "", text: "automatic" }), ...profOpts());
  $("#p-tools").replaceChildren(el("option", { value: "", text: "role default" }), ...profOpts());
  $("#t-profile").append(...profOpts());
  $$("#p-expr button").forEach((b) => b.remove());
  for (const ex of S.meta.expressions) {
    const b = el("button", { class: "btn small", type: "button", text: ex });
    b.addEventListener("click", () => { S.editorExpr = ex; updatePreview(); });
    $("#p-expr").append(b);
  }
  S.tools = await api("GET", "/api/tools");
  S.profileTools = S.meta.profile_tools || {};
  await loadPersonas();
  renderToolFilters(); renderTools();
  if (S.meta.busy) setBusy(S.meta.busy);
  if (S.meta.auto_approve) toast("Auto-approve is ON (-y): risky tools will run without asking.", 6000);
  try { const t = sessionStorage.getItem("tab"); if (t) showTab(t); } catch { /* ignore */ }
  connectEvents();
}
boot();
