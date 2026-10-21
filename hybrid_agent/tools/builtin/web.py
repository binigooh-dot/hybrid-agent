"""[TOOLS / web] Read the web without any API key.

Tools: fetch_url, web_search, extract_links, download_file

Every address (and redirect) is checked by core/netguard.py before connecting:
by default these tools only reach the public internet.

web_search tries, in order, and says which one answered:
  1) your self-hosted SearXNG if SEARXNG_URL is set (best: JSON API, no key)
  2) DuckDuckGo's HTML page (no key; it often challenges automated clients)
  3) Marginalia's free public search API (made for programs; results CC-BY-NC-SA)
  4) Wikipedia search
The agent always identifies itself honestly (User-Agent below); it never
pretends to be a browser to get past a site's bot protection.

Etiquette (Wikimedia's rules, followed everywhere): a User-Agent with contact
details (set AGENT_CONTACT to your email or web page: identified clients get
200 requests/minute on Wikipedia instead of 10), and a 429 "Too Many Requests"
answer is honoured via Retry-After.
"""
from __future__ import annotations

import html
import json
import os
import platform
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from ...security.netguard import check_url, opener
from ..registry import S, ToolContext, ToolError, ToolRegistry

CATEGORY = "web"


def user_agent() -> str:
    """Honest, Wikimedia-compliant: name/version (contact) library/version."""
    from ... import __version__
    contact = os.environ.get("AGENT_CONTACT", "").strip() or "self-hosted; owner contact not set"
    return f"HybridAgent/{__version__} ({contact}) Python-urllib/{platform.python_version()}"


class RateLimited(ToolError):
    """HTTP 429 - the site asked us to slow down."""

MAX_BYTES = 2_000_000            # pages read by fetch_url / extract_links
MAX_DOWNLOAD_BYTES = 50_000_000  # files saved by download_file


class _TextExtractor(HTMLParser):
    SKIP = frozenset({"script", "style", "noscript", "svg", "head"})
    BLOCK = frozenset({"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"})

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._skip = 0
        self._href: str | None = None
        self._anchor: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor = []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "a" and self._href:
            self.links.append((" ".join("".join(self._anchor).split()), self._href))
            self._href = None

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)
            if self._href is not None:
                self._anchor.append(data)


def html_to_text(page: str) -> str:
    p = _TextExtractor()
    p.feed(page)
    text = "".join(p.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def policy_for(ctx: ToolContext) -> str:
    return "local" if ctx.allow_private_network else "public"


def http_get(url: str, timeout: int = 30, headers: dict | None = None, max_bytes: int = MAX_BYTES,
             policy: str = "public", strict_size: bool = False) -> tuple[str, bytes]:
    """GET a URL -> (content-type, raw bytes). Shared by web/knowledge tools.

    The address (and every redirect) is checked against `policy` before any
    connection is made. If strict_size, a body larger than max_bytes is an
    error rather than being silently cut off.
    """
    check_url(url, policy)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent(), **(headers or {})})
    for attempt in (1, 2):
        try:
            return _fetch(req, url, timeout, max_bytes, policy, strict_size)
        except urllib.error.HTTPError as e:
            wait = e.headers.get("Retry-After", "") if e.headers else ""
            if e.code == 429 and attempt == 1 and wait.isdigit() and int(wait) <= 5:
                time.sleep(int(wait))           # polite: wait as asked, then one retry
                continue
            if e.code == 429:
                raise RateLimited(f"{urllib.parse.urlsplit(url).hostname} is rate-limiting requests (HTTP 429); "
                                  "try again in a minute.") from None
            raise ToolError(f"HTTP {e.code} fetching {url}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if attempt == 1 and not isinstance(getattr(e, "reason", None), socket.gaierror):
                time.sleep(0.5)                 # one retry for network blips (timeouts, resets)
                continue
            raise ToolError(f"Could not fetch {url}: {getattr(e, 'reason', e)}") from None
    raise AssertionError("unreachable")


def _fetch(req, url: str, timeout: int, max_bytes: int, policy: str, strict_size: bool) -> tuple[str, bytes]:
    with opener(policy).open(req, timeout=timeout) as r:
        declared = int(r.headers.get("Content-Length") or 0)
        if strict_size and declared > max_bytes:
            raise ToolError(f"{url} is {declared / 1e6:.1f} MB, over the {max_bytes / 1e6:.0f} MB limit.")
        data = r.read(max_bytes + 1)
        if len(data) > max_bytes and strict_size:
            raise ToolError(f"{url} is larger than the {max_bytes / 1e6:.0f} MB limit.")
        return r.headers.get("Content-Type", ""), data[:max_bytes]


def decode(ctype: str, raw: bytes) -> str:
    """Bytes -> text using the server's charset (falls back to UTF-8)."""
    m = re.search(r"charset=([\w-]+)", ctype)
    try:
        return raw.decode(m.group(1) if m else "utf-8", errors="replace")
    except LookupError:  # unknown charset name from the server
        return raw.decode("utf-8", errors="replace")


def http_get_text(url: str, **kw) -> tuple[str, str]:
    ctype, raw = http_get(url, **kw)
    return ctype, decode(ctype, raw)


def http_get_json(url: str, **kw):
    _, body = http_get_text(url, headers={"Accept": "application/json"}, **kw)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise ToolError(f"Expected JSON from {url}, got: {body[:200]}") from None


_BINARY_TYPES = ("application/pdf", "application/zip", "application/octet-stream", "image/", "audio/",
                 "video/", "font/", "application/x-")


def _strip(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def search_duckduckgo(query: str, n: int) -> list[tuple[str, str, str]]:
    _, body = http_get_text("https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query}),
                            headers={"Accept": "text/html", "Accept-Language": "en"}, timeout=10)
    rows = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
                         r'class="result__snippet"[^>]*>(.*?)</a>', body, re.DOTALL):
        href = html.unescape(m.group(1))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        rows.append((_strip(m.group(2)), q.get("uddg", [href])[0], _strip(m.group(3))))
    return rows[:n]


def search_marginalia(query: str, n: int) -> list[tuple[str, str, str]]:
    data = http_get_json(f"https://api.marginalia.nu/public/search/{urllib.parse.quote(query)}?count={n}", timeout=10)
    return [(r.get("title", ""), r.get("url", ""), r.get("description", "")[:300]) for r in data.get("results", [])]


def search_wikipedia(query: str, n: int, lang: str = "en") -> list[tuple[str, str, str]]:
    url = f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "list": "search", "srsearch": query, "srlimit": n, "format": "json"})
    hits = http_get_json(url, timeout=10).get("query", {}).get("search", [])
    return [(h["title"], f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(h["title"].replace(" ", "_")),
             html_to_text(h.get("snippet", ""))) for h in hits]


def search_providers(ctx: ToolContext):
    if ctx.searxng_url:
        base = ctx.searxng_url.rstrip("/")

        def searxng(query: str, n: int):
            url = base + "/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
            return [(r.get("title", ""), r.get("url", ""), r.get("content", ""))
                    for r in http_get_json(url, policy="local").get("results", [])[:n]]
        yield "SearXNG", searxng
    yield "DuckDuckGo", search_duckduckgo
    yield "Marginalia", search_marginalia
    yield "Wikipedia", search_wikipedia


def register(reg: ToolRegistry) -> None:
    t = reg.group(CATEGORY, risk="network")

    @t("fetch_url", "Download a web page or text file and return its readable text.",
       S(url="string"))
    def fetch_url(ctx: ToolContext, url: str):
        ctype, raw = http_get(url, policy=policy_for(ctx))
        if any(ctype.startswith(b) for b in _BINARY_TYPES):
            return f"{url} is binary ({ctype}, {len(raw)} bytes). Use download_file to save it."
        body = decode(ctype, raw)
        text = html_to_text(body) if "html" in ctype or body.lstrip().startswith("<") else body
        return text + ("\n...[page truncated at 2 MB]" if len(raw) >= MAX_BYTES else "")

    @t("web_search", "Search the web. Returns titles, URLs and snippets. Follow up with fetch_url.",
       S(query="string", max_results="integer?|Default 8"))
    def web_search(ctx: ToolContext, query: str, max_results: int = 8):
        tried = []
        for name, provider in search_providers(ctx):
            try:
                rows = provider(query, max_results)
            except ToolError as e:
                tried.append(f"{name}: {e}")
                continue
            if rows:
                return f"(results from {name})\n\n" + "\n\n".join(
                    f"{i}. {t}\n   {u}\n   {s}" for i, (t, u, s) in enumerate(rows[:max_results], 1))
            tried.append(f"{name}: no results")
        return "No results. Tried: " + "; ".join(tried) + ". For reliable search, run SearXNG and set SEARXNG_URL."

    @t("extract_links", "List the links on a web page (text + absolute URL). "
       "Optionally keep only links whose URL or text contains `contains`.",
       S(url="string", contains="string?"))
    def extract_links(ctx: ToolContext, url: str, contains: str | None = None):
        _, body = http_get_text(url, policy=policy_for(ctx))
        p = _TextExtractor()
        p.feed(body)
        seen, rows = set(), []
        for text, href in p.links:
            full = urllib.parse.urljoin(url, href)
            if not full.startswith("http") or full in seen:
                continue
            if contains and contains.lower() not in (full + text).lower():
                continue
            seen.add(full)
            rows.append(f"- {text[:80] or '(no text)'}: {full}")
        return "\n".join(rows[:300]) or "No links found."

    @t("download_file", "Download a file from a URL into the workspace (max 50 MB).",
       S(url="string", path="string|Where to save it in the workspace"), requires_approval=True)
    def download_file(ctx: ToolContext, url: str, path: str):
        from ...security import backup
        from .files import wpath
        dest = wpath(ctx, path)
        ctype, raw = http_get(url, timeout=120, max_bytes=MAX_DOWNLOAD_BYTES, policy=policy_for(ctx),
                              strict_size=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        backup.snapshot(ctx.workspace, dest, "download overwrite")
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(raw)
        tmp.replace(dest)
        return f"Saved {len(raw)} bytes ({ctype or 'unknown type'}) to {path}"
