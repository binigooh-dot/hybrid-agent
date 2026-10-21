"""[RUNTIME / ollama] Keep the local model engine (Ollama) and its models inside the home folder.

    home/runtime/ollama/    the engine, downloaded on request from ollama.com
    home/models/            the model files (OLLAMA_MODELS points here)

The Control panel can install the engine, start/stop it, download ("pull") and
delete models, and shows progress. If Ollama is already installed on the
computer (or already running), that one is used instead - nothing is duplicated.

The engine listens on 127.0.0.1 only, so nothing outside this computer can use it.

Analogy: the engine is the kitchen's oven, models are the recipes. Both live in
the camper van (home folder) and travel with it.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

HOST = "127.0.0.1:11434"
BASE = f"http://{HOST}"
DOWNLOAD_BASE = "https://ollama.com/download/"

# name, download size, RAM needed, suggested tool profile, notes (shown in the Control panel and the guide)
MODELS = [
    ("qwen2.5:1.5b", "~1 GB", "2-3 GB", "minimal", "Tiny and fast; fine for lookups and testing"),
    ("qwen2.5:3b", "~2 GB", "4 GB", "minimal", "Low-end laptops; simple tasks"),
    ("llama3.2:3b", "~2 GB", "4 GB", "minimal", "Similar tier"),
    ("qwen2.5:7b", "~4.7 GB", "8 GB", "core", "Default: good balance"),
    ("llama3.1:8b", "~4.9 GB", "8 GB", "core", "Solid general model; good council contrast to qwen"),
    ("mistral-nemo:12b", "~7 GB", "12 GB", "core / coding", "Strong reasoning for its size"),
    ("qwen2.5:14b", "~9 GB", "16 GB", "coding / research", "Much better at multi-step work"),
    ("qwen2.5:32b", "~20 GB", "24-32 GB / GPU", "full", "Approaches hosted-model quality on many tasks"),
]


def _archive_name() -> str | None:
    """The Ollama download for this computer (names as published on ollama.com/download)."""
    arm = platform.machine().lower() in ("arm64", "aarch64")
    if sys.platform == "win32":
        return f"ollama-windows-{'arm64' if arm else 'amd64'}.zip"
    if sys.platform == "darwin":
        return "Ollama-darwin.zip"
    if sys.platform.startswith("linux"):
        return f"ollama-linux-{'arm64' if arm else 'amd64'}.tar.zst"
    return None


MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,80}(:[A-Za-z0-9._-]{1,40})?$")


def _api(path: str, body: dict | None = None, method: str | None = None, timeout: float = 5):
    req = urllib.request.Request(BASE + path, method=method or ("POST" if body is not None else "GET"),
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    # The engine is on this computer: never send these requests through a web proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=timeout)


class OllamaRuntime:
    def __init__(self, home: Path, log_dir: Path | None = None):
        self.home = home
        self.dir = home / "runtime" / "ollama"
        self.models_dir = home / "models"
        self.log_file = (log_dir or home / "logs") / "ollama.log"
        self.proc: subprocess.Popen | None = None
        self.task: dict = {}                   # current install / pull: {"kind", "name", "done", "total", "status"}
        self._lock = threading.Lock()

    # ------------------------------------------------------------- state
    def binary(self) -> Path | None:
        """The engine to run: ours (in the home folder) first, else a system install."""
        names = ["ollama.exe"] if sys.platform == "win32" else ["bin/ollama", "ollama",
                                                                 "Ollama.app/Contents/Resources/ollama"]
        for n in names:
            if (self.dir / n).is_file():
                return self.dir / n
        found = shutil.which("ollama")
        return Path(found) if found else None

    def running(self) -> bool:
        try:
            with _api("/api/version", timeout=2) as r:
                return r.status == 200
        except OSError:
            return False

    def status(self) -> dict:
        b, up = self.binary(), self.running()
        out: dict[str, Any] = {"installed": bool(b), "bundled": bool(b and self.dir in b.parents), "binary": str(b) if b else None,
               "running": up, "managed": bool(self.proc and self.proc.poll() is None), "url": BASE,
               "models_dir": str(self.models_dir), "models": [], "loaded": [], "version": None,
               "task": self.task, "archive": _archive_name(), "suggested": MODELS}
        if up:
            try:
                with _api("/api/version") as r:
                    out["version"] = json.load(r).get("version")
                with _api("/api/tags") as r:
                    out["models"] = [{"name": m["name"], "size": m.get("size", 0),
                                      "modified": m.get("modified_at", "")[:10]} for m in json.load(r).get("models", [])]
                with _api("/api/ps") as r:
                    out["loaded"] = [m["name"] for m in json.load(r).get("models", [])]
            except (OSError, ValueError):
                pass
        return out

    def disk_used(self) -> dict:
        def size(p: Path) -> int:
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0
        return {"engine_bytes": size(self.dir), "models_bytes": size(self.models_dir)}

    # ------------------------------------------------------------- start / stop
    def start(self) -> str:
        if self.running():
            return "already running"
        b = self.binary()
        if not b:
            raise RuntimeError("The model engine isn't installed yet. Use 'Install engine' first.")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "OLLAMA_MODELS": str(self.models_dir), "OLLAMA_HOST": HOST}
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log = self.log_file.open("ab")
        self.proc = subprocess.Popen([str(b), "serve"], env=env, stdout=log, stderr=log,
                                     stdin=subprocess.DEVNULL, creationflags=flags)
        for _ in range(60):                       # wait up to ~15 s for it to answer
            if self.running():
                return "started"
            if self.proc.poll() is not None:
                break
            time.sleep(0.25)
        raise RuntimeError(f"The engine didn't start; see {self.log_file}")

    def stop(self) -> str:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
            return "stopped"
        return "not started by this app (an external Ollama keeps running)" if self.running() else "not running"

    # ------------------------------------------------------------- background work
    def _background(self, kind: str, name: str, fn: Callable[[dict], None], on_progress: Callable[[dict], None]) -> None:
        with self._lock:
            if self.task and not self.task.get("finished"):
                raise RuntimeError(f"Busy: {self.task['kind']} {self.task['name']} is still running.")
            job: dict = {"kind": kind, "name": name, "done": 0, "total": 0, "status": "starting"}
            self.task = job

        def run():
            try:
                fn(job)
                job.update(status="done", finished=True)
            except Exception as e:  # noqa: BLE001 - reported to the GUI
                job.update(status=f"failed: {e}", finished=True, error=True)
            on_progress(dict(job))
        on_progress(dict(job))
        threading.Thread(target=run, daemon=True, name=f"runtime-{kind}").start()

    def install(self, on_progress: Callable[[dict], None]) -> None:
        """Download the engine from ollama.com into home/runtime/ollama (about 1.6 GB on Windows)."""
        name = _archive_name()
        if not name:
            raise RuntimeError("No Ollama download for this operating system.")
        if name.endswith(".zst") and not (shutil.which("zstd") or sys.version_info >= (3, 14)):
            raise RuntimeError("Unpacking needs `zstd` (Linux: sudo apt install zstd), or install Ollama "
                               "from https://ollama.com/download - the Control panel will use it.")

        def work(job: dict):
            from ..security.guards import ensure_disk_space
            self.dir.mkdir(parents=True, exist_ok=True)
            archive = self.dir.parent / name
            req = urllib.request.Request(DOWNLOAD_BASE + name, headers={"User-Agent": "HybridAgent"})
            with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310 - fixed https://ollama.com URL
                total = int(r.headers.get("Content-Length") or 0)
                ensure_disk_space(self.dir, int(total * 3 / 1e6) + 512)   # archive + unpacked + headroom
                job.update(total=total, status="downloading")
                with archive.open("wb") as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
                        job["done"] += len(chunk)
                        on_progress(dict(job))
            job.update(status="unpacking")
            on_progress(dict(job))
            try:
                _extract(archive, self.dir)
            finally:
                archive.unlink(missing_ok=True)
            b = self.binary()
            if b and os.name == "posix":
                b.chmod(0o755)
        self._background("install", "engine", work, on_progress)

    def pull(self, model: str, on_progress: Callable[[dict], None]) -> None:
        """Download a model into home/models via the engine (progress streamed from Ollama)."""
        model = model.strip()
        if not MODEL_NAME.match(model) or ".." in model:
            raise ValueError("model names look like qwen2.5:7b")
        if not self.running():
            raise RuntimeError("Start the engine first.")

        def work(job: dict):
            with _api("/api/pull", {"model": model, "stream": True}, timeout=3600) as r:
                for line in r:
                    d = json.loads(line or b"{}")
                    if d.get("error"):
                        raise RuntimeError(d["error"])
                    job.update(status=d.get("status", ""), total=d.get("total") or job["total"],
                                     done=d.get("completed") or job["done"])
                    on_progress(dict(job))
        self._background("pull", model, work, on_progress)

    def delete(self, model: str) -> None:
        with _api("/api/delete", {"model": model}, method="DELETE"):
            pass


def _extract(archive: Path, dest: Path) -> None:
    """Unpack zip / tar.zst, refusing any entry that would land outside `dest` (zip-slip)."""
    dest = dest.resolve()

    def inside(name: str) -> bool:
        target = (dest / name).resolve()
        return target == dest or dest in target.parents
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            bad = [n for n in z.namelist() if not inside(n)]
            if bad:
                raise RuntimeError(f"unsafe paths in archive: {bad[:3]}")
            z.extractall(dest)  # noqa: S202  # nosec B202 - every member checked above
        return
    if sys.version_info >= (3, 14):
        from compression import zstd  # type: ignore[import-not-found]  # novermin - only on 3.14+
        stream = zstd.open(archive)
        tar = tarfile.open(fileobj=stream, mode="r|")
    else:
        proc = subprocess.Popen(["zstd", "-dc", str(archive)], stdout=subprocess.PIPE)
        tar = tarfile.open(fileobj=proc.stdout, mode="r|")
    with tar:
        for member in tar:
            if not inside(member.name) or (member.issym() and not inside(os.path.join(os.path.dirname(member.name),
                                                                                       member.linkname))):
                raise RuntimeError(f"unsafe path in archive: {member.name}")
            tar.extract(member, dest, filter="data") if hasattr(tarfile, "data_filter") else \
                tar.extract(member, dest)
