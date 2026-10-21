"""[TOOLS / network] Low-level network utilities (no keys).

Tools: http_request, check_url, dns_lookup, check_port
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

from ..registry import S, ToolContext, ToolError, ToolRegistry
from .web import UA

CATEGORY = "network"


def register(reg: ToolRegistry) -> None:
    t = lambda *a, **k: reg.tool(*a, category=CATEGORY, risk="network", **k)  # noqa: E731

    @t("http_request", "Make an HTTP request (any method) - e.g. to call a local service or a "
       "public JSON API. Returns status, headers and body. Non-GET requests ask for approval.",
       S(url="string",
         method={"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"], "optional": True},
         headers={"type": "object", "description": "Extra request headers", "optional": True},
         body="string?|Request body (send JSON as a string)"))
    def http_request(ctx: ToolContext, url: str, method: str = "GET", headers: dict | None = None,
                     body: str | None = None):
        if not url.startswith(("http://", "https://")):
            raise ToolError("Only http:// and https:// URLs are allowed.")
        if method != "GET" and not ctx.approver("http_request", {"method": method, "url": url},
                                                f"{method} request may change remote data"):
            raise ToolError("User declined the request.")
        req = urllib.request.Request(url, method=method, data=body.encode() if body else None,
                                     headers={"User-Agent": UA, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                status, hdrs, data = r.status, dict(r.headers), r.read(1_000_000)
        except urllib.error.HTTPError as e:
            status, hdrs, data = e.code, dict(e.headers), e.read(1_000_000)
        except (urllib.error.URLError, TimeoutError) as e:
            raise ToolError(f"Request failed: {e}")
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
        if not url.startswith(("http://", "https://")):
            raise ToolError("Only http:// and https:// URLs are allowed.")
        start = time.monotonic()
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return {"status": r.status, "final_url": r.url,
                        "ms": round((time.monotonic() - start) * 1000)}
        except urllib.error.HTTPError as e:
            return {"status": e.code, "ms": round((time.monotonic() - start) * 1000)}
        except (urllib.error.URLError, TimeoutError) as e:
            return {"status": "unreachable", "error": str(e)}

    @t("dns_lookup", "Resolve a hostname to its IP addresses.", S(hostname="string"))
    def dns_lookup(ctx: ToolContext, hostname: str):
        try:
            infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror as e:
            raise ToolError(f"Lookup failed: {e}")
        return sorted({i[4][0] for i in infos})

    @t("check_port", "Check whether a TCP port is open on a host (e.g. is my local server running?).",
       S(host="string", port="integer", timeout="number?|Seconds, default 3"))
    def check_port(ctx: ToolContext, host: str, port: int, timeout: float = 3):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return f"{host}:{port} is OPEN"
        except OSError as e:
            return f"{host}:{port} is CLOSED or unreachable ({e})"
