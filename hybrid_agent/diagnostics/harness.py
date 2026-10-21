"""[DIAGNOSTICS / harness] Guard rails that make the safety drills themselves harmless.

While drills run:
  * NetworkTripwire  - every outbound TCP connection is recorded; anything that
                       isn't loopback is refused before a packet is sent. A drill
                       can then check "did the code even TRY to reach 169.254.169.254?"
  * ProcessTripwire  - any subprocess whose command line looks destructive is
                       refused, so a drill can never delete or damage anything
                       even if the protection it is testing is broken.
  * Sandbox          - a fresh temporary workspace, deleted afterwards.

Analogy: a fire drill uses a smoke machine, not a real fire. The tripwires
are the smoke machine's off-switch.
"""
from __future__ import annotations

import http.client
import re
import shutil
import socket
import subprocess
import tempfile
import threading
from pathlib import Path

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_DESTRUCTIVE = re.compile(r"\brm\b|\bmkfs|\bdd\b|shutdown|reboot|\bkill\b|chmod\s+-R|chown\s+-R|"
                          r"\bfind\b.*-delete|>\s*/dev/(sd|hd|nvme|disk|mmcblk)|\bformat\b|Remove-Item|\bdel\b\s+/", re.I)


class TripwireTriggered(RuntimeError):
    pass


class NetworkTripwire:
    def __init__(self):
        self.attempts: list[str] = []
        self._lock = threading.Lock()
        self._orig_create = socket.create_connection
        self._orig_connect = http.client.HTTPConnection.connect

    def _check(self, host: str) -> None:
        with self._lock:
            self.attempts.append(host)
        if host not in _LOOPBACK:
            raise OSError(f"[drill tripwire] blocked connection to {host}")

    def __enter__(self):
        tw = self

        def create_connection(address, *a, **k):
            tw._check(str(address[0]))
            return tw._orig_create(address, *a, **k)

        def connect(conn_self):
            tw._check(str(conn_self.host))
            return tw._orig_connect(conn_self)

        socket.create_connection = create_connection  # type: ignore[assignment]  # deliberate patch
        http.client.HTTPConnection.connect = connect  # type: ignore[method-assign]  # deliberate patch
        return self

    def __exit__(self, *_exc):
        socket.create_connection = self._orig_create
        http.client.HTTPConnection.connect = self._orig_connect  # type: ignore[method-assign]

    def tried(self, host: str) -> bool:
        return any(host == a for a in self.attempts)


class ProcessTripwire:
    def __init__(self):
        self._orig = subprocess.Popen.__init__
        self.refused: list[str] = []

    def __enter__(self):
        tw = self
        orig = self._orig

        def init(p_self, args, *a, **k):
            text = args if isinstance(args, str) else " ".join(map(str, args))
            if _DESTRUCTIVE.search(text):
                tw.refused.append(text)
                raise TripwireTriggered(f"[drill tripwire] refused destructive command: {text[:120]}")
            return orig(p_self, args, *a, **k)

        subprocess.Popen.__init__ = init  # type: ignore[method-assign, assignment]  # deliberate patch
        return self

    def __exit__(self, *_exc):
        subprocess.Popen.__init__ = self._orig  # type: ignore[method-assign]


class Sandbox:
    """A temporary workspace that is always removed."""

    def __enter__(self) -> Path:
        self.path = Path(tempfile.mkdtemp(prefix="agent-drill-"))
        return self.path

    def __exit__(self, *_exc):
        shutil.rmtree(self.path, ignore_errors=True)
