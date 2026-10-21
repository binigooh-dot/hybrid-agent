"""[TOOLS / web] Read the web without any API key.

Tools: fetch_url, web_search, extract_links, download_file

web_search uses, in order:
  1) a self-hosted SearXNG instance if SEARXNG_URL is set (JSON API, no key)
  2) DuckDuckGo's HTML results page (no key; best-effort - it can
     rate-limit or change its markup)
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from ...core.safety import resolve_in_workspace
from ..registry import S, ToolContext, ToolError, ToolRegistry

CATEGORY = "web"
UA = "Mozilla/5.0 (compatible; hybrid-agent/0.2)"
MAX_BYTES = 2_000_000


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}

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


def http_get(url: str, timeout: int = 30, headers: dict | None = None,
             max_bytes: int = MAX_BYTES) -> tuple[str, bytes]:
    """GET a URL -> (content-type, raw bytes). Shared by web/knowledge tools."""
    if not url.startswith(("http://", "https://")):
        raise ToolError("Only http:// and https:// URLs are allowed.")
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.headers.get("Content-Type", ""), r.read(max_bytes)
    except urllib.error.HTTPError as e:
        raise ToolError(f"HTTP {e.code} fetching {url}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise ToolError(f"Could not fetch {url}: {e}")


def http_get_text(url: str, **kw) -> tuple[str, str]:
    ctype, raw = http_get(url, **kw)
    m = re.search(r"charset=([\w-]+)", ctype)
    return ctype, raw.decode(m.group(1) if m else "utf-8", errors="replace")


def http_get_json(url: str, **kw):
    _, body = http_get_text(url, headers={"Accept": "application/json"}, **kw)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise ToolError(f"Expected JSON from {url}, got: {body[:200]}")


def register(reg: ToolRegistry) -> None:
    t = lambda *a, **k: reg.tool(*a, category=CATEGORY, risk="network", **k)  # noqa: E731

    @t("fetch_url", "Download a web page or text file and return its readable text.",
       S(url="string"))
    def fetch_url(ctx: ToolContext, url: str):
        ctype, body = http_get_text(url)
        return html_to_text(body) if "html" in ctype or body.lstrip().startswith("<") else body

    @t("web_search", "Search the web. Returns titles, URLs and snippets. Follow up with fetch_url.",
       S(query="string", max_results="integer?|Default 8"))
    def web_search(ctx: ToolContext, query: str, max_results: int = 8):
        if ctx.searxng_url:
            url = ctx.searxng_url.rstrip("/") + "/search?" + urllib.parse.urlencode(
                {"q": query, "format": "json"})
            results = http_get_json(url).get("results", [])[:max_results]
            rows = [(r.get("title", ""), r.get("url", ""), r.get("content", "")) for r in results]
        else:
            url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
            _, body = http_get_text(url)
            rows = []
            strip = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s)).strip()  # noqa: E731
            for m in re.finditer(
                    r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
                    r'class="result__snippet"[^>]*>(.*?)</a>', body, re.DOTALL):
                href = html.unescape(m.group(1))
                q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                rows.append((strip(m.group(2)), q.get("uddg", [href])[0], strip(m.group(3))))
                if len(rows) >= max_results:
                    break
        if not rows:
            return "No results (the search provider may be rate-limiting; try again or set SEARXNG_URL)."
        return "\n\n".join(f"{i}. {t}\n   {u}\n   {s}" for i, (t, u, s) in enumerate(rows, 1))

    @t("extract_links", "List the links on a web page (text + absolute URL). "
       "Optionally keep only links whose URL or text contains `contains`.",
       S(url="string", contains="string?"))
    def extract_links(ctx: ToolContext, url: str, contains: str | None = None):
        _, body = http_get_text(url)
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
        dest = resolve_in_workspace(ctx.workspace, path)
        ctype, raw = http_get(url, timeout=120, max_bytes=50_000_000)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return f"Saved {len(raw)} bytes ({ctype or 'unknown type'}) to {path}"
