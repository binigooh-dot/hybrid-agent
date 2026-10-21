"""[TESTS / helpers] Shared fixtures: temp workspaces, registries, and tiny local HTTP servers.

Every test runs offline: no API key, no model, no internet.
"""
from __future__ import annotations

import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from hybrid_agent.core.messages import ToolCall
from hybrid_agent.tools import ToolContext, build_full_registry


def make_registry(tmp: str | None = None, approve: bool = True, **kw):
    ctx = ToolContext(workspace=Path(tmp or tempfile.mkdtemp()), approver=lambda *a: approve, **kw)
    return build_full_registry(ctx)


class ToolTestCase:
    """Mixin: self.tmp workspace + self.call(name, **args) -> ToolResult."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = Path(self.tmp)
        self.reg = make_registry(self.tmp)

    def call(self, name, **args):
        return self.reg.execute(ToolCall("t", name, args))

    def ok(self, name, **args) -> str:
        r = self.call(name, **args)
        assert not r.is_error, f"{name} failed: {r.content}"
        return r.content


def serve(test, handler_cls) -> str:
    """Start an HTTP server on a free port for the duration of a test; return its base URL."""
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    test.addCleanup(srv.server_close)
    test.addCleanup(srv.shutdown)
    return f"http://127.0.0.1:{srv.server_port}"


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = (json.dumps(body) if not isinstance(body, (str, bytes)) else body)
        data = data.encode() if isinstance(data, str) else data
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
