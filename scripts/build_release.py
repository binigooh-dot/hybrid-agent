"""[SCRIPTS / release] Build a shippable release: integrity manifest, wheel, sdist, checksums.

    pip install build            # once
    python scripts/build_release.py

Steps:
  1. writes hybrid_agent/MANIFEST.sha256 (SHA-256 of every package file), so an
     installed copy can detect corruption or tampering (`doctor`, `diagnose`, GUI Safety tab)
  2. builds the wheel and source archive into dist/
  3. writes dist/SHA256SUMS for the downloads themselves
  4. removes the manifest from the source tree again (it describes a release, not a checkout)
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hybrid_agent import __version__
from hybrid_agent.security.audit import write_manifest


def main() -> int:
    dist = ROOT / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    for junk in ROOT.glob("hybrid_agent/**/__pycache__"):
        shutil.rmtree(junk, ignore_errors=True)
    manifest = write_manifest(ROOT / "hybrid_agent")
    print(f"manifest: {len(manifest.read_text(encoding='utf-8').splitlines())} files")
    try:
        subprocess.run([sys.executable, "-m", "build", "--outdir", str(dist), str(ROOT)], check=True)
    finally:
        manifest.unlink(missing_ok=True)
        shutil.rmtree(ROOT / "build", ignore_errors=True)
        for egg in ROOT.glob("*.egg-info"):
            shutil.rmtree(egg, ignore_errors=True)
    sums = "".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n" for f in sorted(dist.iterdir()))
    (dist / "SHA256SUMS").write_text(sums, encoding="utf-8")
    print(f"\nhybrid-agent {__version__} built:\n{sums}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
