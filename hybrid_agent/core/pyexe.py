"""[CORE / pyexe] How to start "a Python" - as a normal install, or inside the packaged app.

Normally that's just sys.executable. In the packaged app (HybridAgent.exe) sys.executable
is the app itself, so starting it would open a second Studio. Instead the app has a hidden
mode, `HybridAgent.exe --hybrid-python ...`, that behaves like the python command
(-c CODE, -m MODULE, - for stdin, or a script path), using the Python built into the app.

  internal_command()  for the agent's own helpers (regex worker, sandbox limiter):
                      always the app's own Python - predictable, nothing else needed
  user_command()      for run_python / run_tests: a real Python installed on the computer
                      if there is one (it has your packages), else the built-in one

Analogy: a Swiss army knife with a hidden blade - same handle, different tool.
"""
from __future__ import annotations

import functools
import runpy
import shutil
import sys

from .home import frozen

FLAG = "--hybrid-python"


def internal_command() -> list[str]:
    return [sys.executable, FLAG] if frozen() else [sys.executable]


@functools.lru_cache(maxsize=1)
def user_command() -> list[str]:
    if not frozen():
        return [sys.executable]
    for name in ("python3", "python", "py"):
        found = shutil.which(name)
        # Skip the Windows Store stub (WindowsApps\python.exe), which opens the Store instead of running code.
        if found and "windowsapps" not in found.lower():
            return [found, "-3"] if name == "py" else [found]
    return internal_command()


def emulate(argv: list[str]) -> int:
    """Act like `python ARGV` (called by the packaged launcher for --hybrid-python)."""
    args = list(argv)
    while args and args[0] in ("-I", "-S", "-E", "-B", "-u", "-s", "-X"):
        if args.pop(0) == "-X" and args and args.pop(0) == "utf8":       # UTF-8 mode: stdio in UTF-8
            for stream in (sys.stdin, sys.stdout, sys.stderr):
                try:
                    stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
                except (AttributeError, ValueError):
                    pass
    if not args:
        print("usage: --hybrid-python [-c code | -m module | - | script] [args]", file=sys.stderr)
        return 2
    first = args.pop(0)
    try:
        if first == "-c":
            code = args.pop(0)
            sys.argv = ["-c", *args]
            exec(compile(code, "<string>", "exec"), {"__name__": "__main__"})  # noqa: S102  # nosec B102 - this IS a python interpreter
        elif first == "-m":
            module = args.pop(0)
            sys.argv = [module, *args]
            runpy.run_module(module, run_name="__main__", alter_sys=True)
        elif first == "-":
            sys.argv = ["-", *args]
            exec(compile(sys.stdin.read(), "<stdin>", "exec"), {"__name__": "__main__"})  # noqa: S102  # nosec B102
        else:
            sys.argv = [first, *args]
            runpy.run_path(first, run_name="__main__")
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return 0
