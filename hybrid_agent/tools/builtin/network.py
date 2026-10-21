"""[TOOLS / network] Low-level network utilities (no keys).

Tools: http_request, check_url, dns_lookup, check_port

These are meant for YOUR services too (a local dev server, Ollama...), so they
use the "local" network policy: loopback and private addresses are allowed,
link-local / cloud-metadata addresses never are (see core/netguard.py).
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

from ...security import netguard
from ..registry import S, ToolContext, ToolError, ToolRegistry
from .web import UA

CATEGORY = "network"


def register(reg: ToolRegistry) -> None:
    t = reg.group(CATEGORY, risk="network")

    @t("http_request", "Make an HTTP request (any method) - e.g. to call a local service or a "
       "public JSON API. Returns status, headers and body. Non-GET requests ask for approval.",
       S(url="string",
         method={"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"], "optional": True},
         headers={"type": "object", "description": "Extra request headers", "optional": True},
         body="string?|Request body (send JSON as a string)"))
    def http_request(ctx: ToolContext, url: str, method: str = "GET", headers: dict | None = None,
                     body: str | None = None):
        netguard.check_url(url, "local")
        if method != "GET" and not ctx.approver("http_request", {"method": method, "url": url},
                                                f"{method} request may change remote data"):
            raise ToolError("User declined the request.")
        req = urllib.request.Request(url, method=method, data=body.encode() if body else None,
                                     headers={"User-Agent": UA, **(headers or {})})
        try:
            with netguard.opener("local").open(req, timeout=30) as r:
                status, hdrs, data = r.status, dict(r.headers), r.read(1_000_000)
        except urllib.error.HTTPError as e:
            status, hdrs, data = e.code, dict(e.headers), e.read(1_000_000)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ToolError(f"Request failed: {getattr(e, 'reason', e)}") from None
        text = data.decode(errors="replace")
        try:
            text = json.dumps(json.loads(text), indent=2)[:15000]
        except (json.JSONDecodeError, ValueError):
            pass
        keep = {k: v for k, v in hdrs.items() if k.lower() in
                {"content-type", "content-length", "location", "retry-after", "date"}}
        return f"HTTP {status}\nheaders: {json.dumps(keep)}\n\n{text}"

    @t("check_url", "Check whether a URL is up: status code, final URL after redirects, response time.",
       S(url="string"))
    def check_url(ctx: ToolContext, url: str):
        netguard.check_url(url, "local")
        start = time.monotonic()
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": UA})
        try:
            with netguard.opener("local").open(req, timeout=20) as r:
                return {"status": r.status, "final_url": r.url,
                        "ms": round((time.monotonic() - start) * 1000)}
        except urllib.error.HTTPError as e:
            return {"status": e.code, "ms": round((time.monotonic() - start) * 1000)}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return {"status": "unreachable", "error": str(getattr(e, "reason", e))}

    @t("dns_lookup", "Resolve a hostname to its IP addresses.", S(hostname="string"))
    def dns_lookup(ctx: ToolContext, hostname: str):
        try:
            infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror as e:
            raise ToolError(f"Lookup failed: {e}") from None
        return sorted({i[4][0] for i in infos})

    @t("check_port", "Check whether a TCP port is open on a host (e.g. is my local server running?).",
       S(host="string", port="integer", timeout="number?|Seconds, default 3"))
    def check_port(ctx: ToolContext, host: str, port: int, timeout: float = 3):
        netguard.check_host(host, "local")
        if not 1 <= port <= 65535:
            raise ToolError("Port must be 1-65535.")
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return f"{host}:{port} is OPEN"
        except OSError as e:
            return f"{host}:{port} is CLOSED or unreachable ({e})"
