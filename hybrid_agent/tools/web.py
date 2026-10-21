"""Web tools that need no API key.

fetch_url   - download a page and turn HTML into readable text (stdlib only).
web_search  - 1) a self-hosted SearXNG instance if SEARXNG_URL is set (JSON
                 API, no key), otherwise
              2) DuckDuckGo's HTML results page (no key, best-effort: it can
                 rate-limit or change its markup).
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from .registry import ToolContext, ToolError, ToolRegistry

UA = "Mozilla/5.0 (compatible; hybrid-agent/0.1)"
MAX_BYTES = 2_000_000


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(page: str) -> str:
    p = _TextExtractor()
    p.feed(page)
    text = "".join(p.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _get(url: str, timeout: int = 30) -> tuple[str, str]:
    if not url.startswith(("http://", "https://")):
        raise ToolError("Only http:// and https:// URLs are allowed.")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = r.headers.get("Content-Type", "")
            body = r.read(MAX_BYTES).decode(r.headers.get_content_charset() or "utf-8", errors="replace")
            return ctype, body
    except urllib.error.HTTPError as e:
        raise ToolError(f"HTTP {e.code} fetching {url}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise ToolError(f"Could not fetch {url}: {e}")


def register(reg: ToolRegistry) -> None:

    @reg.tool("fetch_url",
              "Download a web page or text file and return its readable text.",
              {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]})
    def fetch_url(ctx: ToolContext, url: str):
        ctype, body = _get(url)
        return html_to_text(body) if "html" in ctype or body.lstrip().startswith("<") else body

    @reg.tool("web_search",
              "Search the web. Returns titles, URLs and snippets. Follow up with fetch_url.",
              {"type": "object", "properties": {
                  "query": {"type": "string"},
                  "max_results": {"type": "integer", "description": "Default 8"}},
               "required": ["query"]})
    def web_search(ctx: ToolContext, query: str, max_results: int = 8):
        if ctx.searxng_url:
            url = ctx.searxng_url.rstrip("/") + "/search?" + urllib.parse.urlencode(
                {"q": query, "format": "json"})
            _, body = _get(url)
            results = json.loads(body).get("results", [])[:max_results]
            rows = [(r.get("title", ""), r.get("url", ""), r.get("content", "")) for r in results]
        else:
            url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
            _, body = _get(url)
            rows = []
            for m in re.finditer(
                    r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
                    r'class="result__snippet"[^>]*>(.*?)</a>', body, re.DOTALL):
                href = html.unescape(m.group(1))
                q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                href = q.get("uddg", [href])[0]
                strip = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s)).strip()
                rows.append((strip(m.group(2)), href, strip(m.group(3))))
                if len(rows) >= max_results:
                    break
        if not rows:
            return "No results (the search provider may be rate-limiting; try again or set SEARXNG_URL)."
        return "\n\n".join(f"{i}. {t}\n   {u}\n   {s}" for i, (t, u, s) in enumerate(rows, 1))
