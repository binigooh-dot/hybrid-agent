"""[GUI / server] The local web server behind Agent Studio. Standard library only.

Security model (it runs on YOUR computer, so it is locked down):
  * listens on 127.0.0.1 only - unreachable from your network
  * a random token is generated per launch; every page/API call needs it
  * Host and Origin headers are checked (DNS-rebinding / cross-site protection)
  * strict Content-Security-Policy; model output is always rendered as text
  * request bodies capped at 1 MB; only whitelisted static files are served
  * risky tools still need YOUR click in the browser (Deny after 3 minutes)
"""
from __future__ import annotations

import hmac
import json
import platform
import queue
import secrets
import shutil
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
from ..core.errors import ToolError
from ..council.protocols import PROTOCOLS
from ..council.roles import ROLES
from ..personas import EXPRESSIONS, Persona, delete_persona, load_personas, random_face, render_all, save_persona
from ..personas.faces import COLORS, EYES, HAIR, MOUTHS, NOSES, SHAPES
from ..tools import PROFILES, ToolContext, build_full_registry, build_registry
from .jobs import ApprovalBroker, EventBus, JobBusy, JobManager

STATIC = Path(__file__).resolve().parent / "static"
STATIC_FILES = {"app.js": "text/javascript", "app.css": "text/css", "favicon.svg": "image/svg+xml"}
MAX_BODY = 1_000_000
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class HTTPError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class App:
    """All GUI state. One instance per server."""

    def __init__(self, cfg: Config, port: int):
        self.cfg, self.port = cfg, port
        self.token = secrets.token_urlsafe(24)
        self.bus = EventBus()
        self.broker = ApprovalBroker(self.bus, auto_approve=cfg.auto_approve)
        self.jobs = JobManager(self.bus, self.broker)
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self._chat: Agent | None = None
        self._chat_key: tuple | None = None
        self._meta: tuple[float, dict] | None = None
        self._lock = threading.Lock()

    def check_token(self, value: str | None) -> bool:
        return bool(value) and hmac.compare_digest(str(value).encode(), self.token.encode())

    def personas(self) -> dict[str, Persona]:
        return load_personas(self.cfg.persona_dir)

    @staticmethod
    def persona_payload(p: Persona) -> dict:
        return {**p.to_dict(), "builtin": p.builtin, "faces": render_all(p.face)}

    def tools(self) -> list[dict]:
        return [{"name": t.name, "category": t.category, "risk": t.risk, "approval": t.requires_approval,
                 "description": t.description, "parameters": t.parameters}
                for t in build_full_registry(ToolContext(workspace=self.cfg.workspace)).tools()]

    def meta(self) -> dict:
        now = time.monotonic()
        if not self._meta or now - self._meta[0] > 30:          # building backends isn't free: cache 30 s
            try:
                backend = build_backend(self.cfg).describe()
            except Exception as e:  # noqa: BLE001 - shown in the GUI instead of failing to load
                backend = f"unavailable ({e})"
            ctx = ToolContext(workspace=self.cfg.workspace)
            self._meta = (now, {
                "version": __version__, "backend": backend, "workspace": str(self.cfg.workspace.resolve()),
                "auto_approve": self.cfg.auto_approve, "safe_mode": self.cfg.safe_mode, "os": platform.system(),
                "profiles": list(PROFILES), "profile_tools": {p: build_registry(ctx, p).names() for p in PROFILES},
                "roles": {k: {"title": r.title, "tools": r.tools} for k, r in ROLES.items()},
                "protocols": {k: p.description for k, p in PROTOCOLS.items()}, "expressions": list(EXPRESSIONS),
                "face_parts": {"hair": list(HAIR), "shape": list(SHAPES), "eyes": list(EYES), "nose": list(NOSES),
                               "mouth": list(MOUTHS), "colors": COLORS}})
        return {**self._meta[1], "busy": self.jobs.status()}

    def safety(self) -> dict:
        """Everything protecting the computer, for the Safety tab."""
        from ..security.audit import verify_manifest
        from ..security.backup import list_backups
        from ..security.protected import protected_paths
        from ..security.sandbox import strict_available
        tool, mode = strict_available(), self.cfg.sandbox
        sandbox = "off" if mode == "off" else f"strict ({tool})" if tool and mode in {"auto", "strict"} else "limits only"
        return {"sandbox": sandbox, "require_sandbox": self.cfg.require_sandbox, "safe_mode": self.cfg.safe_mode,
                "auto_approve": self.cfg.auto_approve, "min_free_mb": self.cfg.min_free_mb,
                "disk_free_gb": round(shutil.disk_usage(self.cfg.workspace).free / 1e9, 1),
                "protected": len(protected_paths()), "workspace": str(self.cfg.workspace.resolve()),
                "audit_log": str(self.cfg.log_dir / "audit.jsonl") if self.cfg.log_dir else None,
                "backups": list_backups(self.cfg.workspace)[:50], "manifest": verify_manifest()}

    # ------------------------------------------------------------ jobs
    def chat_agent(self, persona_id: str | None, profile: str | None) -> Agent:
        key = (persona_id or "", profile or "")
        with self._lock:
            if self._chat is None or self._chat_key != key:
                backend = build_backend(self.cfg)
                claude = isinstance(backend, RouterBackend)
                ctx = ToolContext.from_config(self.cfg, approver=self.broker.approver("chat"),
                                              ask_user=self.broker.asker("chat"),
                                              local_backend=build_local_backend(self.cfg) if claude else None)
                tools = build_registry(ctx, profile or ("full" if claude else "core"), include_delegate=claude,
                                       safe_mode=self.cfg.safe_mode)
                system, name = DEFAULT_SYSTEM_PROMPT.format(os=platform.system()), "chat"
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
        return self.jobs.start("chat", lambda: {"answer": agent.run(message[:20000]), "usage": agent.usage},
                               cancel=agent.cancel)

    def start_council(self, body: dict) -> str:
        from ..council import Council
        question = str(body.get("question", "")).strip()
        ids = [str(p) for p in body.get("personas", [])][:8]
        protocol = body.get("protocol", "roundtable")
        if not question or not ids:
            raise HTTPError(400, "give a question and at least one persona")
        if protocol not in PROTOCOLS:
            raise HTTPError(400, f"unknown protocol {protocol}")
        options = [str(o).strip() for o in body.get("options", []) if str(o).strip()][:8] or None
        rounds = max(1, min(int(body.get("rounds", 2)), 5))
        council = Council.from_personas(ids, self.cfg, chair=body.get("chair") or None,
                                        on_event=lambda kind, d: self.bus.publish(kind, **d),
                                        approver=self.broker.approver("council"), ask_user=self.broker.asker("council"))

        def run():
            self.bus.publish("council_setup", chair=council.chair, members=list(council.members),
                             participants=council.participants, question=question, protocol=protocol)
            result = council.deliberate(question, protocol=protocol, rounds=rounds, options=options)
            path = result.save(self.cfg.log_dir)
            return {"final_answer": result.final_answer, "tally": result.tally, "options": result.options,
                    "protocol": result.protocol, "transcript": str(path) if path else "(logging off)",
                    "seconds": result.seconds, "usage": result.usage}
        return self.jobs.start("council", run, cancel=council.cancel)


# ======================================================================= HTTP
ROUTES: dict[tuple[str, str], str] = {}
PREFIX_ROUTES: dict[tuple[str, str], str] = {}
PUBLIC = {"/", "/static/app.js", "/static/app.css", "/static/favicon.svg"}   # the index checks its own token


def route(method: str, path: str, prefix: bool = False):
    def deco(fn):
        (PREFIX_ROUTES if prefix else ROUTES)[(method, path)] = fn.__name__
        return fn
    return deco


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = "AgentStudio", ""
    app: App

    def log_message(self, *_args):  # quiet; the GUI is the log
        pass

    # ------------------------------------------------------- plumbing
    def _headers(self, status: int, ctype: str, length: int | None = None, csp: str = CSP, **extra: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        for k, v in {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                     "Cache-Control": "no-store", "Content-Security-Policy": csp, **extra}.items():
            self.send_header(k, v)
        self.end_headers()

    def _send(self, status: int, body, ctype: str = "application/json", csp: str = CSP):
        data = body if isinstance(body, bytes) else (
            body.encode() if isinstance(body, str) else json.dumps(body, default=str).encode())
        text = ctype.startswith(("text", "application/json"))
        self._headers(status, ctype + ("; charset=utf-8" if text else ""), len(data), csp)
        self.wfile.write(data)

    def _body(self) -> dict:
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise HTTPError(415, "send JSON")
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            remaining = min(n, MAX_BODY * 8)   # drain (bounded) so the client sees the 413, then close
            while remaining > 0 and (chunk := self.rfile.read(min(65536, remaining))):
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
        app = self.app
        try:
            if self.headers.get("Host", "") not in app.allowed_hosts:
                raise HTTPError(403, "bad Host header (DNS-rebinding protection)")
            origin = self.headers.get("Origin")
            if origin and urllib.parse.urlsplit(origin).netloc not in app.allowed_hosts:
                raise HTTPError(403, "cross-origin request refused")
            url = urllib.parse.urlsplit(self.path)
            path, query = url.path, dict(urllib.parse.parse_qsl(url.query))
            name = ROUTES.get((method, path)) or next(
                (h for (m, p), h in PREFIX_ROUTES.items() if m == method and path.startswith(p)), None)
            if name is None:
                raise HTTPError(404, "not found")
            if path not in PUBLIC and not (app.check_token(self.headers.get("X-Agent-Token"))
                                           or app.check_token(query.get("token"))):
                raise HTTPError(401, "missing or wrong token - open the link printed in the terminal")
            getattr(self, name)(path, query)
        except HTTPError as e:
            self._send(e.status, {"error": str(e)})
        except JobBusy as e:
            self._send(409, {"error": str(e)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, ToolError) as e:
            self._send(400, {"error": str(e)})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    # --------------------------------------------------------- pages
    @route("GET", "/")
    def page_index(self, path, query):
        if not self.app.check_token(query.get("token")):
            self._send(401, "<h1>Agent Studio</h1><p>Open the full link (with <code>?token=</code>) printed in "
                            "the terminal where you started the GUI.</p>", "text/html")
            return
        self._send(200, (STATIC / "index.html").read_bytes(), "text/html")

    @route("GET", "/static/", prefix=True)
    def page_static(self, path, query):
        name = path.removeprefix("/static/")
        if name not in STATIC_FILES:
            raise HTTPError(404, "not found")
        self._send(200, (STATIC / name).read_bytes(), STATIC_FILES[name])

    @route("GET", "/guide")
    def page_guide(self, path, query):
        from .guide import build_guide_html
        nonce = secrets.token_urlsafe(16)
        self._send(200, build_guide_html(nonce=nonce, cfg=self.app.cfg), "text/html",
                   csp=CSP.replace("script-src 'self'", f"script-src 'nonce-{nonce}'"))

    # ----------------------------------------------------------- api
    @route("GET", "/api/meta")
    def api_meta(self, path, query):
        self._send(200, self.app.meta())

    @route("GET", "/api/tools")
    def api_tools(self, path, query):
        self._send(200, self.app.tools())

    @route("GET", "/api/personas")
    def api_personas(self, path, query):
        self._send(200, [self.app.persona_payload(p) for p in self.app.personas().values()])

    @route("POST", "/api/personas")
    def api_save_persona(self, path, query):
        body = {k: v for k, v in self._body().items() if k not in {"builtin", "faces"}}
        p = Persona.from_dict(body)
        save_persona(p, self.app.cfg.persona_dir)
        self._send(200, self.app.persona_payload(p))

    @route("DELETE", "/api/personas/", prefix=True)
    def api_delete_persona(self, path, query):
        self._send(200, {"deleted": delete_persona(path.removeprefix("/api/personas/"), self.app.cfg.persona_dir)})

    @route("POST", "/api/face")
    def api_face(self, path, query):
        self._send(200, {"faces": render_all(self._body().get("face"))})

    @route("GET", "/api/face/random")
    def api_random_face(self, path, query):
        self._send(200, {"face": random_face(query.get("seed") or secrets.token_hex(4))})

    @route("GET", "/api/doctor")
    def api_doctor(self, path, query):
        from ..cli.doctor import run_checks
        self._send(200, [{"status": s, "check": c, "detail": d, "required": m}
                         for s, c, d, m in run_checks(self.app.cfg)])

    @route("GET", "/api/safety")
    def api_safety(self, path, query):
        self._send(200, self.app.safety())

    @route("POST", "/api/restore")
    def api_restore(self, path, query):
        from ..security.backup import restore
        restored = restore(self.app.cfg.workspace, str(self._body().get("id", "")))
        self.app.bus.publish("restored", path=restored)
        self._send(200, {"restored": restored})

    @route("POST", "/api/chat")
    def api_chat(self, path, query):
        self._send(202, {"job_id": self.app.start_chat(self._body())})

    @route("POST", "/api/chat/reset")
    def api_chat_reset(self, path, query):
        with self.app._lock:
            self.app._chat = None
        self._send(200, {"ok": True})

    @route("POST", "/api/council")
    def api_council(self, path, query):
        self._send(202, {"job_id": self.app.start_council(self._body())})

    @route("POST", "/api/diagnose")
    def api_diagnose(self, path, query):
        from ..diagnostics.runner import run_all
        only = self._body().get("only") or None
        self._send(202, {"job_id": self.app.jobs.start("diagnose", lambda: run_all(only))})

    @route("POST", "/api/stop")
    def api_stop(self, path, query):
        self._send(200, {"stopping": self.app.jobs.stop()})

    @route("POST", "/api/approve")
    def api_approve(self, path, query):
        b = self._body()
        ok = self.app.broker.answer(str(b.get("request_id")), bool(b.get("allow")))
        self._send(200 if ok else 404, {"ok": ok})

    @route("POST", "/api/answer")
    def api_answer(self, path, query):
        b = self._body()
        ok = self.app.broker.answer(str(b.get("request_id")), str(b.get("text", ""))[:5000])
        self._send(200 if ok else 404, {"ok": ok})

    @route("GET", "/api/events")
    def api_events(self, path, query):
        """Server-Sent Events stream. Reconnecting clients resume after Last-Event-ID."""
        q = self.app.bus.subscribe(int(self.headers.get("Last-Event-ID") or query.get("after") or 0))
        self._headers(200, "text/event-stream", Connection="keep-alive")
        try:
            self.wfile.write(b"retry: 2000\n\n")
            while True:
                try:
                    e = q.get(timeout=15)
                    self.wfile.write(f"id: {e['id']}\ndata: {json.dumps(e, default=str)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except OSError:
            pass
        finally:
            self.app.bus.unsubscribe(q)


class GuiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(cfg: Config, port: int = 8765) -> tuple[GuiServer, App]:
    """Build (but don't start) the server. port=0 picks a free port (tests)."""
    srv = GuiServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    app = App(cfg, srv.server_port)
    srv.RequestHandlerClass = type("BoundHandler", (Handler,), {"app": app})
    return srv, app


def serve(cfg: Config, port: int = 8765, open_browser: bool = True) -> int:
    srv, app = create_server(cfg, port)
    url = f"http://127.0.0.1:{app.port}/?token={app.token}"
    print(f"\n  Agent Studio is running:\n\n    {url}\n\n  Only this computer can connect; the link changes every "
          f"launch.\n  Press Ctrl+C to stop.\n")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping...")
        app.jobs.stop()
    finally:
        srv.server_close()
    return 0
