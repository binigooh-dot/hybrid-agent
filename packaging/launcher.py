"""[PACKAGING / launcher] The entry point compiled into HybridAgent.exe.

    HybridAgent.exe                 start the Studio (home folder + model engine + GUI + scheduler)
    HybridAgent.exe doctor          any CLI command: chat, doctor, tools, council, diagnose, gui
    HybridAgent.exe --hybrid-python ...   internal: act as a Python interpreter (see core/pyexe.py)

Imports stay inside main() so the internal Python mode starts fast and light.
"""
import sys

CLI = {"chat", "doctor", "tools", "council", "diagnose", "gui"}


def _wine_compat() -> None:
    """Running under Wine (Linux)? Wine 9 lacks CopyFile2, which Python 3.12 uses for file copies on
    Windows - make shutil use its older method instead of crashing. Real Windows is unaffected."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.ntdll.wine_get_version  # noqa: B018 - only exists under Wine
    except (AttributeError, OSError):
        return
    import _winapi
    if hasattr(_winapi, "CopyFile2"):
        del _winapi.CopyFile2


def main() -> int:
    _wine_compat()
    args = sys.argv[1:]
    if args[:1] == ["--hybrid-python"]:
        from hybrid_agent.core.pyexe import emulate
        return emulate(args[1:])
    for stream in (sys.stdout, sys.stderr):          # box-drawing banner + names on any console
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if args and args[0] in CLI:
        from hybrid_agent.cli.main import main as cli
        from hybrid_agent.core.home import apply_home, find_home
        home = find_home()
        if home:
            apply_home(home)
        return cli(args)
    from hybrid_agent.app import main as studio
    return studio(args)


if __name__ == "__main__":
    double_clicked = len(sys.argv) == 1 and getattr(sys, "frozen", False)   # decided before main() edits argv
    code = main()
    if code and double_clicked:
        try:                                          # double-clicked: keep the window open to read the error
            input("\nSomething went wrong (see above). Press Enter to close...")
        except EOFError:
            pass
    sys.exit(code)
