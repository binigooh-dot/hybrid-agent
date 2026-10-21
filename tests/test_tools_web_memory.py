"""[TESTS / tools: web + network + knowledge parsing + memory + documents]

Web tools are tested against a local HTTP server, never the internet.
"""
from __future__ import annotations

import json
import unittest

from hybrid_agent.core.messages import ToolCall
from hybrid_agent.tools.builtin.documents import bm25_rank, chunk_text, tokenize
from hybrid_agent.tools.builtin.knowledge import parse_feed
from hybrid_agent.tools.builtin.web import html_to_text

from .helpers import QuietHandler, ToolTestCase, make_registry, serve

PAGE = ("<html><head><title>t</title><script>evil()</script></head><body><h1>Hello</h1>"
        "<p>World <a href='/next'>Next page</a> <a href='https://other.org/x'>Other</a></p></body></html>")
RSS = ("<rss><channel><item><title>News 1</title><link>http://a/1</link><pubDate>Mon</pubDate>"
       "<description>&lt;b&gt;Big&lt;/b&gt; story</description></item></channel></rss>")


class Site(QuietHandler):
    def do_GET(self):
        if self.path == "/":
            return self.send(200, PAGE, "text/html; charset=utf-8")
        if self.path == "/data.json":
            return self.send(200, {"ok": True})
        return self.send(404, "nope", "text/plain")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        return self.send(201, {"got": self.rfile.read(n).decode()})


class WebToolTests(ToolTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.url = serve(self, Site)
        # The test server runs on this computer, which web tools refuse by default.
        self.reg = make_registry(self.tmp, allow_private_network=True)

    def test_loopback_blocked_by_default(self):
        r = make_registry(self.tmp).execute(ToolCall("t", "fetch_url", {"url": self.url + "/"}))
        self.assertTrue(r.is_error)
        self.assertIn("private network", r.content)

    def test_fetch_and_links(self):
        text = self.ok("fetch_url", url=self.url + "/")
        self.assertIn("Hello", text)
        self.assertNotIn("evil", text)
        links = self.ok("extract_links", url=self.url + "/")
        self.assertIn(f"Next page: {self.url}/next", links)
        self.assertNotIn("Other", self.ok("extract_links", url=self.url + "/", contains="next"))
        self.assertIn("HTTP 404", self.call("fetch_url", url=self.url + "/missing").content)
        self.assertTrue(self.call("fetch_url", url="file:///etc/passwd").is_error)

    def test_download_http_check(self):
        self.ok("download_file", url=self.url + "/data.json", path="d/data.json")
        self.assertEqual(json.loads((self.ws / "d/data.json").read_text(encoding="utf-8")), {"ok": True})
        self.assertIn("HTTP 201", self.ok("http_request", url=self.url + "/", method="POST", body="ping"))
        self.assertIn('"status": 200', self.ok("check_url", url=self.url + "/"))
        port = int(self.url.rsplit(":", 1)[1])
        self.assertIn("OPEN", self.ok("check_port", host="127.0.0.1", port=port))
        self.assertIn("127.0.0.1", self.ok("dns_lookup", hostname="localhost"))

    def test_parsers(self):
        self.assertEqual(html_to_text("<p>a</p><p>b</p>"), "a\nb")
        items = parse_feed(RSS)
        self.assertEqual((items[0]["title"], items[0]["summary"]), ("News 1", "Big story"))
        atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>P</title>'
                '<link href="http://x"/><updated>2026</updated></entry></feed>')
        self.assertEqual(parse_feed(atom)[0]["link"], "http://x")


class OnlineEtiquetteAndProxyTests(unittest.TestCase):
    """Behind a proxy, names the computer can't resolve itself still pass the safety checks."""

    def test_proxy_lets_unresolvable_public_names_through(self):
        import socket
        from unittest import mock

        from hybrid_agent.core.errors import ToolError
        from hybrid_agent.security import netguard
        fail = mock.patch("socket.getaddrinfo", side_effect=socket.gaierror(-2, "no DNS"))
        with fail, mock.patch.object(netguard, "proxied", return_value=True):
            netguard.check_url("https://en.wikipedia.org/wiki/Ada_Lovelace")            # allowed: the proxy resolves it
            for bad in ("http://169.254.169.254/", "http://localhost:11434/", "http://metadata.google.internal/",
                        "http://printer.local/", "http://10.0.0.1/"):
                with self.assertRaises(ToolError, msg=bad):
                    netguard.check_url(bad)
        with fail, mock.patch.object(netguard, "proxied", return_value=False), self.assertRaises(ToolError):
            netguard.check_url("https://en.wikipedia.org/")                             # no proxy: must resolve

    def test_user_agent_is_honest_and_has_contact(self):
        import os
        from unittest import mock

        from hybrid_agent.tools.builtin.web import user_agent
        with mock.patch.dict(os.environ, {"AGENT_CONTACT": "me@example.org"}):
            ua = user_agent()
        self.assertTrue(ua.startswith("HybridAgent/"))
        self.assertIn("me@example.org", ua)
        self.assertNotIn("Mozilla", ua)

    def test_search_falls_back_and_names_the_provider(self):
        from unittest import mock

        from hybrid_agent.core.errors import ToolError
        from hybrid_agent.tools.builtin import web
        reg = make_registry()
        with mock.patch.object(web, "search_duckduckgo", return_value=[]), \
                mock.patch.object(web, "search_marginalia", side_effect=ToolError("timeout")), \
                mock.patch.object(web, "search_wikipedia", return_value=[("Ada", "https://w/Ada", "maths")]):
            out = reg.execute(ToolCall("1", "web_search", {"query": "ada"})).content
        self.assertIn("results from Wikipedia", out)
        self.assertIn("https://w/Ada", out)


class MemoryAndDocsTests(ToolTestCase, unittest.TestCase):
    def test_memory_roundtrip(self):
        self.ok("remember", key="fav_colour", value="green", tags=["prefs"])
        self.assertIn("green", self.ok("recall", query="colour"))
        self.assertIn("green", self.ok("recall", query="prefs"))
        self.ok("forget", key="fav_colour")
        self.assertIn("Nothing", self.ok("recall", query="colour"))

    def test_document_search(self):
        self.ok("write_file", path="docs/cats.md", content="Cats purr and sleep a lot.\n" * 3)
        self.ok("write_file", path="docs/rockets.md", content="Rockets need fuel and oxygen to reach orbit.\n")
        self.assertTrue(self.call("search_documents", query="x").is_error)  # no index yet
        self.assertIn("2 files", self.ok("index_documents"))
        top = self.ok("search_documents", query="orbit fuel", top_k=1)
        self.assertIn("rockets.md", top)
        self.assertNotIn("cats.md", top)

    def test_bm25_and_chunks(self):
        docs = [{"tf": dict(__import__("collections").Counter(tokenize(t))), "len": len(tokenize(t)), "t": t}
                for t in ("apple banana", "banana banana cherry", "dog")]
        ranked = bm25_rank("banana", docs)
        self.assertEqual(ranked[0][1]["t"], "banana banana cherry")
        chunks = chunk_text("\n".join(f"line {i} " + "x" * 50 for i in range(100)), size=500, overlap=100)
        self.assertGreater(len(chunks), 5)
        self.assertEqual(chunks[0][0], 1)


if __name__ == "__main__":
    unittest.main()
