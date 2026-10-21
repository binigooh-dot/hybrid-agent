"""[SECURITY / regex worker] Child-process side of run_regex_isolated().

Reads one JSON request on stdin, writes one JSON result on stdout. Runs in its
own process so a catastrophic regex can be killed by the parent's timeout.

ops:
  finditer  {pattern, flags, text, limit}            -> [[start, end, match, groups], ...]
  subn      {pattern, flags, text, replacement, count} -> [new_text, n]
  grep      {pattern, flags, files: [[rel, abs]], limit} -> ["rel:line: text", ...]
"""
import json
import re
import sys
from typing import Any


def main() -> None:
    req = json.loads(sys.stdin.read())
    rx = re.compile(req["pattern"], req.get("flags", 0))
    op = req["op"]
    out: list[Any]
    if op == "finditer":
        out = [[m.start(), m.end(), m.group(0)[:200], list(m.groups())]
               for _, m in zip(range(req.get("limit", 200)), rx.finditer(req["text"]), strict=False)]
    elif op == "subn":
        out = list(rx.subn(req["replacement"], req["text"], count=req.get("count", 0)))
    elif op == "grep":
        out = []
        for rel, path in req["files"]:
            try:
                with open(path, errors="replace", encoding="utf-8") as fh:
                    for i, line in enumerate(fh, 1):
                        if rx.search(line):
                            out.append(f"{rel}:{i}: {line.rstrip()[:300]}")
                            if len(out) >= req.get("limit", 200):
                                break
            except OSError:
                continue
            if len(out) >= req.get("limit", 200):
                break
    else:
        raise SystemExit(f"unknown op {op}")
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
