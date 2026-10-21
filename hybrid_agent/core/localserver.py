"""[CORE / localserver] The HTTP server used for 127.0.0.1: the GUI, the drills' test sites, the tests.

Python's HTTPServer looks up its own name when it starts (socket.getfqdn, a reverse DNS query). On some
computers that query stalls for many seconds - GitHub's macOS runners hung on it - which would also make the
app slow to open. A server that only listens on this computer doesn't need its DNS name, so skip it.
"""
from __future__ import annotations

import socketserver
from http.server import ThreadingHTTPServer


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)            # bind only - no socket.getfqdn() lookup
        host, port = self.server_address[:2]
        self.server_name, self.server_port = str(host), int(port)
