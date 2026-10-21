"""[GUI / server] The local web server behind the GUI. Standard library only.

Security model (it runs on YOUR computer, so it is locked down):
  * listens on 127.0.0.1 only - unreachable from your network
  * a random token is generated per launch; every page/API call needs it
    (the link printed in the terminal carries it)
  * Host and Origin headers are checked, so a malicious website you visit
    can't talk to it through your browser (DNS-rebinding / CSRF protection)
  * strict Content-Security-Policy: only the app's own scripts run; model
    output is always rendered as text, never as HTML
  * request bodies are capped at 1 MB; only whitelisted static files are served
  * risky tools still need YOUR click in the browser (Deny after 3 minutes)
"""
from __future__ import annotations

import hmac
import json
import mimetypes
import platform
import queue
import re
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import __version__
from ..backends import build_backend, build_local_backend
from ..backends.router import RouterBackend
from ..core.agent import DEFAULT_SYSTEM_PROMPT, Agent
from ..core.config import Config
from ..council.protocols import PROTOCOLS
from ..council.roles import ROLES
from ..personas import (
    EXPRESSIONS,
    Persona,
    delete_persona,
    load_personas,
    random_face,
    render_all,
    render_face,
    save_persona,
)
from ..tools import PROFILES, ToolContext, build_full_registry, build_registry
from .jobs import ApprovalBroker, EventBus, JobBusy, JobManager

STATIC = Path(__file__).resolve().parent / "static"
STATIC_FILES = {"app.js": "text/javascript", "app.css": "text/css", "favicon.svg": "image/svg+xml"}
MAX_BODY = 1_000_000
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class HTTPError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class App:
    """All GUI state. One instance per server."""

    def __init__(self, cfg: Config, port: int):
        self.cfg = cfg
        self.port = port
        self.token = secrets.token_urlsafe(24)
        self.bus = EventBus()
        self.broker = ApprovalBroker(self.bus, auto_approve=cfg.auto_approve)
        self.jobs = JobManager(self.bus, self.broker)
        self._chat: Agent | None = None
        self._chat_key: tuple | None = None
        self._lock = threading.Lock()
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    # ------------------------------------------------------------ helpers
    def check_token(self, value: str | None) -> bool:
        if not value:
            return False
        return hmac.compare_digest(value.encode(), self.token.encode())

    def personas(self) -> dict[str, Persona]:
        return load_personas(self.cfg.persona_dir)

    def persona_payload(self, p: Persona) -> dict:
        return {**p.to_dict(), "builtin": p.builtin, "faces": render_all(p.face, 160, p.name)}

    def tool_payload(self) -> list[dict]:
        reg = build_full_registry(ToolContext(workspace=self.cfg.workspace))
        return [{"name": n, "category": reg[n].category, "risk": reg[n].risk,
                 "approval": reg[n].requires_approval, "description": reg[n].description,
                 "parameters": reg[n].parameters} for n in reg.names()]

    def meta(self) -> dict:
        try:
            backend = build_backend(self.cfg).describe()
        except Exception as e:  # show the problem in the GUI rather than failing to load  # noqa: BLE001 - deliberate boundary: report the failure, never crash
            backend = f"unavailable ({e})"
        return {"version": __version__, "backend": backend, "workspace": str(self.cfg.workspace.resolve()),
                "auto_approve": self.cfg.auto_approve, "profiles": list(PROFILES),
                "profile_tools": {p: build_registry(ToolContext(workspace=self.cfg.workspace), p).names()
                                  for p in PROFILES},
                "roles": {k: {"title": r.title, "tools": r.tools} for k, r in ROLES.items()},
                "protocols": {k: p.description for k, p in PROTOCOLS.items()},
                "expressions": list(EXPRESSIONS), "os": platform.system(), "busy": self.jobs.status()}

    # --------------------------------------------------------------- chat
    def chat_agent(self, persona_id: str | None, profile: str | None) -> Agent:
        key = (persona_id or "", profile or "")
        with self._lock:
            if self._chat is None or self._chat_key != key:
                backend = build_backend(self.cfg)
                uses_claude = isinstance(backend, RouterBackend)
                ctx = ToolContext(workspace=self.cfg.workspace, approver=self.broker.approver("chat"),
                                  ask_user=self.broker.asker("chat"), max_output=self.cfg.max_tool_output,
                                  shell_timeout=self.cfg.shell_timeout, searxng_url=self.cfg.searxng_url,
                                  allow_private_network=self.cfg.allow_private_network,
                                  local_backend=build_local_backend(self.cfg) if uses_claude else None)
                prof = profile or ("full" if uses_claude else "core")
                tools = build_registry(ctx, prof, include_delegate=uses_claude)
                system = DEFAULT_SYSTEM_PROMPT.format(os=platform.system())
                name = "chat"
                if persona_id:
                    p = self.personas().get(persona_id)
                    if not p:
                        raise HTTPError(404, f"unknown persona {persona_id}")
                    system += f"\n\nYou are {p.name}, {p.title}.\n{p.persona_text()}"
                    name = p.id
                def relay(kind: str, data: dict) -> None:
                    self.bus.publish("agent", kind=kind, data=data)
                self._chat = Agent(backend, tools, system_prompt=system, max_steps=self.cfg.max_steps,
                                   log_dir=self.cfg.log_dir, name=name, on_event=relay,
                                   context_chars=self.cfg.context_chars())
                self._chat_key = key
            return self._chat

    def start_chat(self, body: dict) -> str:
        message = str(body.get("message", "")).strip()
        if not message:
            raise HTTPError(400, "message is empty")
        agent = self.chat_agent(body.get("persona") or None, body.get("profile") or None)

        def run():
            answer = agent.run(message[:20000])
            return {"answer": answer, "usage": agent.usage, "persona": body.get("persona")}
        return self.jobs.start("chat", run, cancel=agent.cancel)

    # ------------------------------------------------------------ council
    def start_council(self, body: dict) -> str:
        from ..council import Council
        question = str(body.get("question", "")).strip()
        ids = [str(p) for p in body.get("personas", [])][:8]
        if not question or not ids:
            raise HTTPError(400, "give a question and at least one persona")
        protocol = body.get("protocol", "roundtable")
        if protocol not in PROTOCOLS:
            raise HTTPError(400, f"unknown protocol {protocol}")
        options = [str(o).strip() for o in body.get("options", []) if str(o).strip()][:8] or None
        rounds = max(1, min(int(body.get("rounds", 2)), 5))
        try:
            council = Council.from_personas(ids, self.cfg, chair=body.get("chair") or None,
                                            on_event=lambda kind, d: self.bus.publish(kind, **d),
                                            approver=self.broker.approver("council"),
                                            ask_user=self.broker.asker("council"))
        except ValueError as e:
            raise HTTPError(400, str(e)) from None
        def run():
            self.bus.publish("council_setup", chair=council.chair, members=list(council.members),
                             participants=council.participants, question=question, protocol=protocol)
            result = council.deliberate(question, protocol=protocol, rounds=rounds, options=options)
            path = result.save(self.cfg.log_dir)
            return {"final_answer": result.final_answer, "tally": result.tally, "options": result.options,
                    "protocol": result.protocol, "transcript": str(path) if path else "(logging off)",
                    "seconds": result.seconds,
                    "usage": result.usage}
        return self.jobs.start("council", run, cancel=council.cancel)

    # ---------------------------------------------------------- diagnose
    def start_diagnose(self, body: dict) -> str:
        from ..diagnostics.runner import run_all
        only = body.get("only") or None
        return self.jobs.start("diagnose", lambda: run_all(only))


# ======================================================================= HTTP
def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AgentStudio"
        sys_version = ""

        def log_message(self, *_args):  # quiet; the GUI is the log
            pass

        # ------------------------------------------------------- plumbing
        def _headers(self, status: int, ctype: str, length: int | None = None, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            if length is not None:
                self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", (extra or {}).pop("csp", CSP))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()

        def _send(self, status: int, body, ctype: str = "application/json", extra: dict | None = None):
            data = body if isinstance(body, bytes) else (
                body.encode() if isinstance(body, str) else json.dumps(body, default=str).encode())
            self._headers(status, ctype + ("; charset=utf-8" if ctype.startswith(("text", "application/json")) else ""),
                          len(data), extra)
            self.wfile.write(data)

        def _guard(self) -> tuple[str, dict]:
            host = self.headers.get("Host", "")
            if host not in app.allowed_hosts:
                raise HTTPError(403, "bad Host header (DNS-rebinding protection)")
            origin = self.headers.get("Origin")
            if origin and urllib.parse.urlsplit(origin).netloc not in app.allowed_hosts:
                raise HTTPError(403, "cross-origin request refused")
            url = urllib.parse.urlsplit(self.path)
            return url.path, dict(urllib.parse.parse_qsl(url.query))

        def _need_token(self, query: dict) -> None:
            if not (app.check_token(self.headers.get("X-Agent-Token")) or app.check_token(query.get("token"))):
                raise HTTPError(401, "missing or wrong token - open the link printed in the terminal")

        def _body(self) -> dict:
            if "application/json" not in self.headers.get("Content-Type", ""):
                raise HTTPError(415, "send JSON")
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                # Read (and discard) a bounded amount so the client receives the 413
                # instead of a broken connection, then close.
                remaining = min(n, MAX_BODY * 8)
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                self.close_connection = True
                raise HTTPError(413, "request too large")
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                raise HTTPError(400, "invalid JSON") from None
            if not isinstance(data, dict):
                raise HTTPError(400, "JSON body must be an object")
            return data

        def _dispatch(self, method: str) -> None:
            try:
                path, query = self._guard()
                handler = ROUTES.get((method, path))
                if handler is None:
                    for (m, prefix), h in PREFIX_ROUTES.items():
                        if m == method and path.startswith(prefix):
                            handler = h
                            break
                if handler is None:
                    raise HTTPError(404, "not found")
                if path not in PUBLIC:
                    self._need_token(query)
                handler(self, path, query)
            except HTTPError as e:
                self._send(e.status, {"error": str(e)})
            except JobBusy as e:
                self._send(409, {"error": str(e)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except ValueError as e:
                self._send(400, {"error": str(e)})

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_DELETE(self):
            self._dispatch("DELETE")

        # --------------------------------------------------------- pages
        def page_index(self, path, query):
            if not app.check_token(query.get("token")):
                self._send(401, "<h1>Agent Studio</h1><p>Open the full link (with <code>?token=</code>) printed in "
                                "the terminal where you started the GUI.</p>", "text/html")
                return
            self._send(200, (STATIC / "index.html").read_bytes(), "text/html")

        def page_static(self, path, query):
            name = path.removeprefix("/static/")
            if name not in STATIC_FILES:
                raise HTTPError(404, "not found")
            self._send(200, (STATIC / name).read_bytes(), STATIC_FILES[name])

        def page_guide(self, path, query):
            from .guide import build_guide_html
            nonce = secrets.token_urlsafe(16)
            html = build_guide_html(nonce=nonce, cfg=app.cfg)
            csp = CSP.replace("script-src 'self'", f"script-src 'nonce-{nonce}'")
            self._send(200, html, "text/html", {"csp": csp})

        def page_persona_image(self, path, query):
            name = path.removeprefix("/persona-image/")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}\.[a-z]{3,4}", name) or Path(name).suffix not in IMAGE_EXT:
                raise HTTPError(404, "not found")
            f = (app.cfg.persona_dir / name).resolve()
            if f.parent != app.cfg.persona_dir.resolve() or not f.is_file():
                raise HTTPError(404, "not found")
            self._send(200, f.read_bytes(), mimetypes.guess_type(name)[0] or "application/octet-stream")

        # ----------------------------------------------------------- api
        def api_meta(self, path, query):
            self._send(200, app.meta())

        def api_tools(self, path, query):
            self._send(200, app.tool_payload())

        def api_personas(self, path, query):
            self._send(200, [app.persona_payload(p) for p in app.personas().values()])

        def api_save_persona(self, path, query):
            body = self._body()
            body.pop("builtin", None)
            body.pop("faces", None)
            p = Persona.from_dict(body)
            save_persona(p, app.cfg.persona_dir)
            self._send(200, app.persona_payload(p))

        def api_delete_persona(self, path, query):
            pid = path.removeprefix("/api/personas/")
            self._send(200, {"deleted": delete_persona(pid, app.cfg.persona_dir)})

        def api_face(self, path, query):
            body = self._body()
            self._send(200, {"svg": render_face(body.get("face"), str(body.get("expression", "neutral")), 220)})

        def api_random_face(self, path, query):
            self._send(200, {"face": random_face(query.get("seed") or secrets.token_hex(4))})

        def api_doctor(self, path, query):
            from ..cli.doctor import run_checks
            self._send(200, [{"status": s, "check": c, "detail": d, "required": m}
                             for s, c, d, m in run_checks(app.cfg)])

        def api_status(self, path, query):
            self._send(200, {"busy": app.jobs.status()})

        def api_chat(self, path, query):
            self._send(202, {"job_id": app.start_chat(self._body())})

        def api_chat_reset(self, path, query):
            with app._lock:
                app._chat = None
            self._send(200, {"ok": True})

        def api_council(self, path, query):
            self._send(202, {"job_id": app.start_council(self._body())})

        def api_diagnose(self, path, query):
            self._send(202, {"job_id": app.start_diagnose(self._body())})

        def api_stop(self, path, query):
            self._send(200, {"stopping": app.jobs.stop()})

        def api_approve(self, path, query):
            b = self._body()
            ok = app.broker.answer(str(b.get("request_id")), bool(b.get("allow")))
            self._send(200 if ok else 404, {"ok": ok})

        def api_answer(self, path, query):
            b = self._body()
            ok = app.broker.answer(str(b.get("request_id")), str(b.get("text", ""))[:5000])
            self._send(200 if ok else 404, {"ok": ok})

        def api_events(self, path, query):
            """Server-Sent Events stream. Reconnecting clients resume after Last-Event-ID."""
            after = int(self.headers.get("Last-Event-ID") or query.get("after") or 0)
            q = app.bus.subscribe(after)
            self._headers(200, "text/event-stream", extra={"Connection": "keep-alive"})
            try:
                self.wfile.write(b"retry: 2000\n\n")
                self.wfile.flush()
                while True:
                    try:
                        e = q.get(timeout=15)
                        data = json.dumps(e, default=str)
                        self.wfile.write(f"id: {e['id']}\ndata: {data}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                app.bus.unsubscribe(q)

    H = Handler
    ROUTES = {
        ("GET", "/"): H.page_index, ("GET", "/guide"): H.page_guide,
        ("GET", "/api/meta"): H.api_meta, ("GET", "/api/tools"): H.api_tools,
        ("GET", "/api/personas"): H.api_personas, ("POST", "/api/personas"): H.api_save_persona,
        ("POST", "/api/face"): H.api_face, ("GET", "/api/face/random"): H.api_random_face,
        ("GET", "/api/doctor"): H.api_doctor, ("GET", "/api/status"): H.api_status,
        ("POST", "/api/chat"): H.api_chat, ("POST", "/api/chat/reset"): H.api_chat_reset,
        ("POST", "/api/council"): H.api_council, ("POST", "/api/diagnose"): H.api_diagnose,
        ("POST", "/api/stop"): H.api_stop, ("POST", "/api/approve"): H.api_approve,
        ("POST", "/api/answer"): H.api_answer, ("GET", "/api/events"): H.api_events,
    }
    PREFIX_ROUTES = {("GET", "/static/"): H.page_static, ("DELETE", "/api/personas/"): H.api_delete_persona,
                     ("GET", "/persona-image/"): H.page_persona_image}
    # Pages that check the token themselves (index shows a help page) or contain nothing private.
    PUBLIC = {"/", "/static/app.js", "/static/app.css", "/static/favicon.svg"}
    return Handler


class GuiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(cfg: Config, port: int = 8765) -> tuple[GuiServer, App]:
    """Build (but don't start) the server. port=0 picks a free port (tests)."""
    srv = GuiServer(("127.0.0.1", port), BaseHTTPRequestHandler)  # placeholder, replaced below
    app = App(cfg, srv.server_port)
    srv.RequestHandlerClass = make_handler(app)
    return srv, app


def serve(cfg: Config, port: int = 8765, open_browser: bool = True) -> int:
    srv, app = create_server(cfg, port)
    url = f"http://127.0.0.1:{app.port}/?token={app.token}"
    print(f"\n  Agent Studio running at:\n\n    {url}\n\n  (only this computer can connect; the token "
          f"changes every launch)\n  Press Ctrl+C to stop.\n")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping...")
        app.jobs.stop()
        time.sleep(0.3)
    finally:
        srv.server_close()
    return 0
