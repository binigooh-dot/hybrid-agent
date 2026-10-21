"""[SECURITY / netguard] Decide which network addresses the agent may contact.

Two policies:
  "public" - the open internet only. Blocks this computer (loopback), your
             private network (10.x, 192.168.x, 172.16-31.x, fc00::/7) and
             link-local / cloud-metadata addresses. Used by web + knowledge tools.
  "local"  - also allows loopback and private networks (to call your own local
             services, e.g. Ollama or a dev server). Used by http_request,
             check_url, check_port.
Both always block link-local (169.254.0.0/16, fe80::/10, incl. the cloud
metadata endpoint that hands out credentials), multicast, and reserved ranges.

Every redirect hop is re-checked (GuardedRedirectHandler), so a harmless-looking
URL can't bounce the agent into a forbidden address.

Analogy: a receptionist who checks the visitor list for every door the agent
walks through, not just the front door.

Limitation: the name is resolved here and again by the HTTP client, so a
hostile DNS server could answer differently the second time (DNS rebinding).
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.parse
import urllib.request

from ..core.errors import ToolError

ALWAYS_BLOCKED_HOSTS = {"metadata.google.internal", "metadata", "instance-data", "instance-data.ec2.internal"}
METADATA_IPS = {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("100.100.100.200"),
                ipaddress.ip_address("fd00:ec2::254")}


def _reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, policy: str) -> str | None:
    if ip in METADATA_IPS or ip.is_link_local:
        return "link-local / cloud-metadata address"
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return "multicast/reserved address"
    if policy == "public" and (ip.is_loopback or ip.is_private):
        return "this computer or your private network (allowed only for local-network tools, " \
               "or set AGENT_ALLOW_PRIVATE_NETWORK=1)"
    return None


def check_host(host: str, policy: str = "public") -> None:
    if not host:
        raise ToolError("URL has no host.")
    if host.lower().rstrip(".") in ALWAYS_BLOCKED_HOSTS:
        raise ToolError(f"Blocked host {host}: cloud metadata service.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ToolError(f"Can't resolve {host}: {e}") from None
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        why = _reason(ip, policy)
        if why:
            raise ToolError(f"Blocked {host} ({ip}): {why}.")


def check_url(url: str, policy: str = "public") -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise ToolError("Only http:// and https:// URLs are allowed.")
    check_host(parts.hostname or "", policy)


class GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def __init__(self, policy: str):
        super().__init__()
        self.policy = policy

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, self.policy)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def opener(policy: str) -> urllib.request.OpenerDirector:
    """An urllib opener whose redirects obey the same policy."""
    return urllib.request.build_opener(GuardedRedirectHandler(policy))
