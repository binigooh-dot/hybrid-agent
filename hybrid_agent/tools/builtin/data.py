"""[TOOLS / data] Work with structured data files: CSV, JSON, SQLite, XML.

Tools: csv_read, csv_query, json_query, convert_data, sqlite_query, xml_query
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import statistics
from collections.abc import Callable

from ...security.guards import read_text_limited, resolve_in_workspace
from ...security.xmlsafe import safe_xml_parse
from ..registry import S, ToolContext, ToolError, ToolRegistry

CATEGORY = "data"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_rows(ctx: ToolContext, path: str) -> list[dict]:
    p = resolve_in_workspace(ctx.workspace, path)
    if not p.is_file():
        raise ToolError(f"No such file: {path}")
    text = read_text_limited(p)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def table(rows: list[dict], limit: int = 50) -> str:
    """Render rows as a simple Markdown table."""
    if not rows:
        return "(no rows)"
    cols = list(rows[0].keys())
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows[:limit]:
        out.append("| " + " | ".join(str(r.get(c, ""))[:60] for c in cols) + " |")
    if len(rows) > limit:
        out.append(f"... {len(rows) - limit} more rows")
    return "\n".join(out)


AGGREGATES: dict[str, Callable[[list[float]], float]] = {
    "sum": lambda xs: float(sum(xs)), "mean": statistics.fmean, "min": min, "max": max}

_COND = re.compile(r"^\s*(\w[\w ]*?)\s*(==|!=|>=|<=|>|<|contains)\s*(.+?)\s*$")


def _match(row: dict, cond: str) -> bool:
    m = _COND.match(cond)
    if not m:
        raise ToolError(f"Bad filter '{cond}'. Use e.g. 'age > 30', 'name contains Ann', 'city == Paris'.")
    col, op, val = m.group(1), m.group(2), m.group(3).strip("'\"")
    if col not in row:
        raise ToolError(f"Unknown column '{col}'. Columns: {', '.join(row)}")
    cell = row[col]
    if op == "contains":
        return val.lower() in str(cell).lower()
    a, b = _num(cell), _num(val)
    if a is None or b is None:
        a, b = str(cell), val
    return {"==": a == b, "!=": a != b, ">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]


def json_path(data, path: str):
    """'users[0].name' / 'items.*.price' style lookup."""
    cur = [data]
    for part in re.findall(r"[^.\[\]]+|\[\d+\]|\*", path):
        nxt: list = []
        for c in cur:
            if part == "*":
                nxt.extend(c.values() if isinstance(c, dict) else c if isinstance(c, list) else [])
            elif part.startswith("["):
                i = int(part[1:-1])
                if isinstance(c, list) and -len(c) <= i < len(c):
                    nxt.append(c[i])
            elif isinstance(c, dict) and part in c:
                nxt.append(c[part])
        cur = nxt
    return cur


def register(reg: ToolRegistry) -> None:
    t = reg.group(CATEGORY)

    @t("csv_read", "Preview a CSV/TSV file: columns, row count, first rows, and per-column "
       "stats (numeric min/max/mean, or distinct values for text).",
       S(path="string", rows="integer?|Rows to show, default 10"))
    def csv_read(ctx: ToolContext, path: str, rows: int = 10):
        data = load_rows(ctx, path)
        if not data:
            return "Empty file."
        stats = []
        for col in data[0]:
            vals = [r[col] for r in data if r.get(col) not in (None, "")]
            nums = [n for n in map(_num, vals) if n is not None]
            if nums and len(nums) == len(vals):
                stats.append(f"- {col}: numeric, min {min(nums):g}, max {max(nums):g}, "
                             f"mean {statistics.fmean(nums):.4g}, {len(data) - len(vals)} empty")
            else:
                distinct = sorted(set(vals))
                sample = ", ".join(distinct[:5]) + (" ..." if len(distinct) > 5 else "")
                stats.append(f"- {col}: text, {len(distinct)} distinct ({sample})")
        return f"{len(data)} rows\n\nColumns:\n" + "\n".join(stats) + "\n\n" + table(data, rows)

    @t("csv_query", "Filter, sort, select columns and aggregate a CSV file. Filters like "
       "['age > 30', 'city == Paris', 'name contains ann'] are ANDed. "
       "group_by + aggregate gives e.g. sum of 'amount' per 'category'.",
       S(path="string",
         where={"type": "array", "items": {"type": "string"}, "optional": True},
         columns={"type": "array", "items": {"type": "string"}, "optional": True},
         sort_by="string?|Column; prefix with '-' for descending",
         group_by="string?",
         aggregate={"type": "string", "enum": ["count", "sum", "mean", "min", "max"], "optional": True},
         value_column="string?|Column to aggregate (not needed for count)",
         limit="integer?|Default 50"))
    def csv_query(ctx: ToolContext, path: str, where: list | None = None, columns: list | None = None,
                  sort_by: str | None = None, group_by: str | None = None, aggregate: str | None = None,
                  value_column: str | None = None, limit: int = 50):
        rows = [r for r in load_rows(ctx, path) if all(_match(r, c) for c in (where or []))]
        if group_by:
            agg = aggregate or "count"
            groups: dict[str, list] = {}
            for r in rows:
                groups.setdefault(r.get(group_by, ""), []).append(r)
            out = []
            for key, grp in groups.items():
                val: float | None
                if agg == "count":
                    val = len(grp)
                else:
                    if not value_column:
                        raise ToolError("value_column is required for sum/mean/min/max.")
                    nums = [n for n in (_num(g.get(value_column)) for g in grp) if n is not None]
                    fn = AGGREGATES[agg]
                    val = round(fn(nums), 6) if nums else None
                out.append({group_by: key, f"{agg}({value_column or ''})": val})
            rows = out
        if sort_by:
            key = sort_by.lstrip("-")
            rows.sort(key=lambda r: (_num(r.get(key)) is None, _num(r.get(key)) or 0, str(r.get(key))),
                      reverse=sort_by.startswith("-"))
        if columns:
            rows = [{c: r.get(c, "") for c in columns} for r in rows]
        return f"{len(rows)} matching rows\n" + table(rows, limit)

    @t("json_query", "Read a value from a JSON file by path, e.g. 'users[0].name' or 'items.*.price'. "
       "Empty path shows the top-level structure.",
       S(path="string|JSON file", query="string?|Path expression"))
    def json_query(ctx: ToolContext, path: str, query: str = ""):
        p = resolve_in_workspace(ctx.workspace, path)
        try:
            data = json.loads(read_text_limited(p))
        except FileNotFoundError:
            raise ToolError(f"No such file: {path}") from None
        except json.JSONDecodeError as e:
            raise ToolError(f"Invalid JSON: line {e.lineno}: {e.msg}") from None
        if not query:
            if isinstance(data, dict):
                return {k: type(v).__name__ + (f"[{len(v)}]" if isinstance(v, (list, dict)) else "")
                        for k, v in data.items()}
            return f"{type(data).__name__} with {len(data) if hasattr(data, '__len__') else 1} items"
        res = json_path(data, query)
        return res[0] if len(res) == 1 else res

    @t("convert_data", "Convert between CSV and JSON files (a JSON list of objects <-> CSV rows).",
       S(source="string", destination="string|Extension decides the output format"), risk="write")
    def convert_data(ctx: ToolContext, source: str, destination: str):
        dst = resolve_in_workspace(ctx.workspace, destination)
        if source.endswith((".csv", ".tsv")) and destination.endswith(".json"):
            rows = load_rows(ctx, source)
            dst.write_text(json.dumps(rows, indent=2))
        elif source.endswith(".json") and destination.endswith((".csv", ".tsv")):
            rows = json.loads(resolve_in_workspace(ctx.workspace, source).read_text())
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                raise ToolError("JSON must be a list of objects to convert to CSV.")
            cols = list(dict.fromkeys(k for r in rows for k in r))
            with dst.open("w", newline="") as f:
                w = csv.DictWriter(f, cols, delimiter="\t" if destination.endswith(".tsv") else ",")
                w.writeheader()
                w.writerows(rows)
        else:
            raise ToolError("Supported: .csv/.tsv -> .json and .json -> .csv/.tsv")
        return f"Converted {source} -> {destination} ({len(rows)} rows)"

    @t("sqlite_query", "Run SQL on a SQLite database file in the workspace. SELECTs are free; "
       "statements that change data ask for approval. Use 'SELECT name, sql FROM sqlite_master' "
       "to see the schema.",
       S(path="string|Database file (created if missing)", sql="string"))
    def sqlite_query(ctx: ToolContext, path: str, sql: str):
        p = resolve_in_workspace(ctx.workspace, path)
        read_only = re.match(r"^\s*(select|with|pragma|explain)\b", sql, re.I) is not None
        if not read_only and not ctx.approver("sqlite_query", {"sql": sql}, "modifies the database"):
            raise ToolError("User declined the write query.")
        uri = f"file:{p}?mode=ro" if read_only else f"file:{p}?mode=rwc"
        try:
            con = sqlite3.connect(uri, uri=True, timeout=10)
        except sqlite3.OperationalError as e:
            raise ToolError(f"Can't open database: {e}") from None
        try:
            cur = con.execute(sql)
            if cur.description:
                cols = [c[0] for c in cur.description]
                rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchmany(500)]
                return f"{len(rows)} rows\n" + table(rows, 100)
            con.commit()
            return f"OK, {cur.rowcount} rows affected."
        except sqlite3.Error as e:
            raise ToolError(f"SQL error: {e}") from None
        finally:
            con.close()

    @t("xml_query", "Find elements in an XML file with an ElementPath expression "
       "(e.g. './/book[@lang=\"en\"]/title'). Returns tag, attributes and text.",
       S(path="string", xpath="string"))
    def xml_query(ctx: ToolContext, path: str, xpath: str):
        p = resolve_in_workspace(ctx.workspace, path)
        if not p.is_file():
            raise ToolError(f"No such file: {path}")
        try:
            found = safe_xml_parse(p).findall(xpath)
        except SyntaxError as err:
            raise ToolError(f"Bad ElementPath expression: {err}") from None
        rows = []
        for el in found[:200]:
            attrs = "".join(f' {k}="{v}"' for k, v in el.attrib.items())
            rows.append(f"<{el.tag}{attrs}> {(el.text or '').strip()[:200]}".rstrip())
        return "\n".join(rows) or "No matches."
