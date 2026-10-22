"""[SCRIPTS / exe] Build the self-contained app: HybridAgent.exe (Windows) or HybridAgent (Linux/macOS).

    pip install pyinstaller
    python scripts/build_exe.py                     # build for this computer
    python scripts/build_exe.py --wine C:/path/python.exe   # Linux -> Windows, via Wine (docs/DEVELOPING.md)

Output (dist/):
    HybridAgent/                       the app folder - copy it anywhere, double-click HybridAgent(.exe)
      HybridAgent(.exe)  _internal/    the program (read-only to the agents)
      MANIFEST.sha256                  integrity manifest of every program file
      START HERE.txt                   five lines: how to start
    HybridAgent-<version>-<os>.zip     the same folder, zipped, + SHA256SUMS

The home/ folder (your settings, files, tasks, models) is created next to the program on first run.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hybrid_agent import __version__
from hybrid_agent.security.audit import write_manifest

START_HERE = """Hybrid Agent {version}

1. Double-click {exe}. Keep the small black window open while you use the app.
2. Press "Set up now". It downloads the AI engine and a model that fits this PC (once).
3. Chat, ask the Council, or schedule Tasks. Everything is saved in the "home" folder here.
Safe by default: agents only change files in home\\workspace and ask before anything risky.
Windows warning "unrecognized app"? Click More info, then Run anyway.
"""


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def version_file(path: Path) -> None:
    nums = tuple(int(x) for x in (__version__.split(".") + ["0", "0", "0"])[:4])
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Hybrid Agent'), StringStruct('FileDescription', 'Hybrid Agent'),
    StringStruct('FileVersion', '{__version__}'), StringStruct('InternalName', 'HybridAgent'),
    StringStruct('OriginalFilename', 'HybridAgent.exe'), StringStruct('ProductName', 'Hybrid Agent'),
    StringStruct('ProductVersion', '{__version__}')])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--python", default=sys.executable, help="Python (with PyInstaller) that builds the app")
    ap.add_argument("--wine", metavar="WIN_PYTHON", help="build the Windows .exe from Linux: path to python.exe")
    ap.add_argument("--out", type=Path, default=ROOT / "dist")
    args = ap.parse_args()
    windows = bool(args.wine) or sys.platform == "win32"
    target = "windows-x64" if windows else f"{sys.platform.replace('darwin', 'macos')}-{platform.machine().lower()}"
    out, work = args.out.resolve(), (ROOT / "build" / f"pyi-{target}").resolve()
    app = out / "HybridAgent"
    shutil.rmtree(app, ignore_errors=True)
    for junk in ROOT.glob("hybrid_agent/**/__pycache__"):
        shutil.rmtree(junk, ignore_errors=True)
    version_file(ROOT / "packaging" / "version_info.txt")
    builder = ["wine", args.wine] if args.wine else [args.python]
    env = {**os.environ, "WINEDEBUG": "-all"} if args.wine else None
    run([*builder, "-m", "PyInstaller", str(ROOT / "packaging" / "HybridAgent.spec"), "--noconfirm", "--clean",
         "--distpath", str(out), "--workpath", str(work)], cwd=ROOT, env=env)
    exe = "HybridAgent.exe" if windows else "HybridAgent"
    if not (app / exe).exists():
        print(f"build failed: {app / exe} missing", file=sys.stderr)
        return 1
    (app / "START HERE.txt").write_text(START_HERE.format(version=__version__, exe=exe), newline="\r\n" if windows else "\n", encoding="utf-8")
    manifest = write_manifest(app)
    print(f"manifest: {len(manifest.read_text(encoding='utf-8').splitlines())} files")
    archive = out / f"HybridAgent-{__version__}-{target}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(app.rglob("*")):
            info = zipfile.ZipInfo.from_file(f, Path("HybridAgent") / f.relative_to(app))
            if f.is_file():
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, f.read_bytes())
    sums = out / "SHA256SUMS"
    lines = dict(line.split("  ", 1)[::-1] for line in sums.read_text(encoding="utf-8").splitlines() if "  " in line) if sums.exists() else {}
    lines[archive.name] = hashlib.sha256(archive.read_bytes()).hexdigest()
    sums.write_text("".join(f"{h}  {n}\n" for n, h in sorted(lines.items())), encoding="utf-8")
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file())
    print(f"\nbuilt {app} ({size / 1e6:.0f} MB) and {archive.name} ({archive.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
