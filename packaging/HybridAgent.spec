# [PACKAGING / spec] PyInstaller recipe for HybridAgent (.exe on Windows, a binary on Linux/macOS).
#
#   python scripts/build_exe.py            # the easy way: builds, writes the integrity manifest, zips
#
# One-folder build ("onedir"): starts faster than a single-file exe and is friendlier to antivirus
# scanners. The console window shows the link and status; closing it stops the app.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = SPECPATH + "/.."

# Standard-library modules kept for the agent's run_python tool when no system Python is installed
# (the app's own Python then runs the code, and it only has what is bundled).
STDLIB_FOR_SCRIPTS = [
    "argparse", "base64", "bisect", "calendar", "collections", "copy", "csv", "dataclasses", "datetime",
    "decimal", "difflib", "email", "enum", "fnmatch", "fractions", "functools", "glob", "gzip", "hashlib",
    "heapq", "html", "html.parser", "http.client", "io", "itertools", "json", "logging", "math", "operator",
    "pathlib", "pprint", "random", "re", "shutil", "sqlite3", "statistics", "string", "struct", "tarfile",
    "tempfile", "textwrap", "time", "typing", "unittest", "urllib.parse", "uuid", "xml.etree.ElementTree",
    "zipfile", "zoneinfo",
]

# Time-zone data: Windows has no system database, so bundle the tzdata package when it's installed.
try:
    TZ_DATA, TZ_IMPORTS = collect_data_files("tzdata"), collect_submodules("tzdata")
except Exception:  # noqa: BLE001 - optional
    TZ_DATA, TZ_IMPORTS = [], []

a = Analysis(
    [ROOT + "/packaging/launcher.py"],
    pathex=[ROOT],
    datas=collect_data_files("hybrid_agent", excludes=["**/__pycache__/*", "MANIFEST.sha256"]) + TZ_DATA,
    hiddenimports=collect_submodules("hybrid_agent") + STDLIB_FOR_SCRIPTS + TZ_IMPORTS,
    excludes=["tkinter", "test", "lib2to3", "pydoc_data", "playwright", "PIL", "fontTools"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="HybridAgent",
    icon=ROOT + "/packaging/HybridAgent.ico",
    version=ROOT + "/packaging/version_info.txt",
    console=True,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="HybridAgent", upx=False)
