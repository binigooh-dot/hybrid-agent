"""[TOOLS / system] Inspect the computer the agent runs on (read-only).

Tools: system_info, disk_usage, env_vars, python_packages

env_vars never reveals values of variables that look like secrets.
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from importlib import metadata

from ...security.sandbox import SECRET_NAME
from ..registry import S, ToolContext, ToolError, ToolRegistry

CATEGORY = "system"


def _mem_gb() -> str:
    try:
        with open("/proc/meminfo") as f:
            info = dict(line.split(":", 1) for line in f)
        total = int(info["MemTotal"].split()[0]) / 1024 ** 2
        avail = int(info["MemAvailable"].split()[0]) / 1024 ** 2
        return f"{avail:.1f} GB free of {total:.1f} GB"
    except (OSError, KeyError, ValueError):
        return "unknown (not Linux)"


def register(reg: ToolRegistry) -> None:
    t = reg.group(CATEGORY)

    @t("system_info", "Operating system, CPU count, memory, Python version, and the workspace path.", S())
    def system_info(ctx: ToolContext):
        return {"os": f"{platform.system()} {platform.release()}", "machine": platform.machine(),
                "cpus": os.cpu_count(), "memory": _mem_gb(),
                "python": sys.version.split()[0], "workspace": str(ctx.workspace.resolve())}

    @t("disk_usage", "Free and used disk space for the drive holding a workspace path.",
       S(path="string?|Default '.'"))
    def disk_usage(ctx: ToolContext, path: str = "."):
        from ...security.guards import resolve_in_workspace
        u = shutil.disk_usage(resolve_in_workspace(ctx.workspace, path))
        gb = 1024 ** 3
        return f"total {u.total / gb:.1f} GB, used {u.used / gb:.1f} GB, free {u.free / gb:.1f} GB " \
               f"({u.free / u.total:.0%} free)"

    @t("env_vars", "List environment variable names (optionally filtered). Values are shown "
       "only for non-secret-looking variables.",
       S(contains="string?|Only names containing this"))
    def env_vars(ctx: ToolContext, contains: str | None = None):
        rows = []
        for k in sorted(os.environ):
            if contains and contains.lower() not in k.lower():
                continue
            v = "<hidden>" if SECRET_NAME.search(k) else os.environ[k][:120]
            rows.append(f"{k}={v}")
        return "\n".join(rows) or "No matching variables."

    @t("python_packages", "List installed Python packages and versions (optionally filtered), "
       "or check if specific ones are installed.",
       S(contains="string?"))
    def python_packages(ctx: ToolContext, contains: str | None = None):
        pk = sorted({(d.metadata["Name"] or "?", d.version) for d in metadata.distributions()},
                    key=lambda x: x[0].lower())
        rows = [f"{n}=={v}" for n, v in pk if not contains or contains.lower() in n.lower()]
        if not rows:
            raise ToolError(f"No installed package matches '{contains}'.")
        return "\n".join(rows)
