"""[TOOLS / archives] Create, list and extract .zip / .tar(.gz/.bz2/.xz) archives.

Tools: archive_list, archive_create, archive_extract

Extraction is protected against "zip-slip" (entries like ../../etc/passwd
that try to write outside the destination folder).
"""
from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

from ...security.guards import resolve_in_workspace
from ..registry import S, ToolContext, ToolError, ToolRegistry

CATEGORY = "archives"
MAX_EXTRACT_BYTES = 1_000_000_000   # total uncompressed size allowed (zip-bomb protection)
MAX_ENTRIES = 20_000


def _is_tar(name: str) -> bool:
    return name.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz"))


def _tar_mode(name: str, write: bool) -> str:
    ext = "gz" if name.endswith((".gz", ".tgz")) else "bz2" if name.endswith(".bz2") \
        else "xz" if name.endswith(".xz") else ""
    return ("w:" if write else "r:") + ext if ext else ("w" if write else "r")


def register(reg: ToolRegistry) -> None:
    t = reg.group(CATEGORY)

    @t("archive_list", "List the files inside a .zip or .tar archive.", S(path="string"))
    def archive_list(ctx: ToolContext, path: str):
        p = resolve_in_workspace(ctx.workspace, path)
        if not p.is_file():
            raise ToolError(f"No such file: {path}")
        if zipfile.is_zipfile(p):
            with zipfile.ZipFile(p) as z:
                rows = [f"{i.filename}  ({i.file_size} B)" for i in z.infolist()]
        elif _is_tar(p.name) or tarfile.is_tarfile(p):
            with tarfile.open(p) as tf:
                rows = [f"{m.name}  ({m.size} B)" for m in tf.getmembers()]
        else:
            raise ToolError("Not a zip or tar archive.")
        return f"{len(rows)} entries\n" + "\n".join(rows[:500])

    @t("archive_create", "Pack files/folders from the workspace into a .zip or .tar.gz archive.",
       S(output="string|e.g. backup.zip or src.tar.gz",
         paths={"type": "array", "items": {"type": "string"}}),
       risk="write")
    def archive_create(ctx: ToolContext, output: str, paths: list):
        out = resolve_in_workspace(ctx.workspace, output)
        root = ctx.workspace.resolve()
        files: list[Path] = []
        for rel in paths:
            p = resolve_in_workspace(ctx.workspace, rel)
            if not p.exists():
                raise ToolError(f"No such path: {rel}")
            files.extend([p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()])
        files = [f for f in files if f != out]
        out.parent.mkdir(parents=True, exist_ok=True)
        if output.endswith(".zip"):
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                for f in files:
                    z.write(f, f.relative_to(root))
        elif _is_tar(output):
            with tarfile.open(out, _tar_mode(output, True)) as tf:  # type: ignore[call-overload]  # mode is computed
                for f in files:
                    tf.add(f, str(f.relative_to(root)))
        else:
            raise ToolError("Output must end in .zip, .tar, .tar.gz, .tgz, .tar.bz2 or .tar.xz")
        return f"Created {output} with {len(files)} files ({out.stat().st_size} B)"

    @t("archive_extract", "Extract a .zip or .tar archive into a workspace folder.",
       S(path="string", destination="string?|Default: folder named after the archive"),
       risk="write")
    def archive_extract(ctx: ToolContext, path: str, destination: str | None = None):
        p = resolve_in_workspace(ctx.workspace, path)
        if not p.is_file():
            raise ToolError(f"No such file: {path}")
        dest_rel = destination or p.name.split(".")[0]
        dest = resolve_in_workspace(ctx.workspace, dest_rel)
        dest.mkdir(parents=True, exist_ok=True)

        def safe(name: str) -> Path:
            target = (dest / name).resolve()
            if target != dest and dest not in target.parents:
                raise ToolError(f"Archive entry '{name}' would escape the destination; aborted.")
            return target

        def check_budget(sizes: list[int]) -> None:
            if len(sizes) > MAX_ENTRIES:
                raise ToolError(f"Archive has {len(sizes)} entries (limit {MAX_ENTRIES}); refusing.")
            if sum(sizes) > MAX_EXTRACT_BYTES:
                raise ToolError(f"Archive would expand to {sum(sizes) / 1e6:.0f} MB (limit "
                                f"{MAX_EXTRACT_BYTES / 1e6:.0f} MB) - possible zip bomb; refusing.")

        if zipfile.is_zipfile(p):
            with zipfile.ZipFile(p) as z:
                infos = z.infolist()
                check_budget([i.file_size for i in infos])
                for i in infos:
                    safe(i.filename)
                # Reviewed (B202): members validated above
                z.extractall(dest, members=infos)  # noqa: S202 - every member is validated above  # nosec B202
                count = len(infos)
        elif tarfile.is_tarfile(p):
            with tarfile.open(p) as tf:
                members = tf.getmembers()
                check_budget([m.size for m in members])
                for m in members:
                    safe(m.name)
                    if m.issym() or m.islnk() or m.isdev():
                        raise ToolError(f"Archive contains a link or device ({m.name}); refusing to extract.")
                try:
                    tf.extractall(dest, members=members, filter="data")  # extra safety on newer Pythons
                except TypeError:  # older 3.10/3.11 patch releases lack filter=; members were checked above
                    # Reviewed (B202): members validated above
                    tf.extractall(dest, members=members)  # noqa: S202 - every member is validated above  # nosec B202
                count = len(members)
        else:
            raise ToolError("Not a zip or tar archive.")
        return f"Extracted {count} entries into {dest_rel}/"
