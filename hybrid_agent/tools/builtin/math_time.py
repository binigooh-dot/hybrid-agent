"""[TOOLS / math + time] Exact numbers and dates, so the model never does mental arithmetic.

Tools (category "math"): calculator, statistics, unit_convert, convert_base
Tools (category "time"): current_time, date_calc, convert_timezone
"""
from __future__ import annotations

import ast
import datetime as dt
import math
import operator
import statistics as st
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..registry import S, ToolContext, ToolError, ToolRegistry

# ------------------------------------------------------------------ calculator
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_FUNCS = {name: getattr(math, name) for name in
          ("sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "log", "log10", "log2", "exp",
           "floor", "ceil", "factorial", "radians", "degrees", "gcd", "lcm", "comb", "perm", "hypot")}
_FUNCS.update(abs=abs, round=round, min=min, max=max)
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def safe_eval(expr: str) -> float | int:
    """Evaluate arithmetic WITHOUT eval(): walk the syntax tree and only allow
    numbers, + - * / // % **, and a whitelist of math functions."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10000:
                raise ToolError("Exponent too large.")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _FUNCS and not node.keywords):
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ToolError(f"Unsupported expression element: {ast.dump(node)[:60]}")
    try:
        return ev(ast.parse(expr.replace("^", "**"), mode="eval"))
    except SyntaxError as e:
        raise ToolError(f"Syntax error: {e.msg}")
    except ZeroDivisionError:
        raise ToolError("Division by zero.")
    except (ValueError, OverflowError) as e:
        raise ToolError(f"Math error: {e}")


# --------------------------------------------------------------- unit convert
# Each unit -> (dimension, factor to the SI base unit)
UNITS = {
    # length (m)
    "mm": ("length", 1e-3), "cm": ("length", 1e-2), "m": ("length", 1), "km": ("length", 1e3),
    "in": ("length", 0.0254), "ft": ("length", 0.3048), "yd": ("length", 0.9144), "mi": ("length", 1609.344),
    "nmi": ("length", 1852),
    # mass (kg)
    "mg": ("mass", 1e-6), "g": ("mass", 1e-3), "kg": ("mass", 1), "t": ("mass", 1000),
    "oz": ("mass", 0.028349523125), "lb": ("mass", 0.45359237), "st": ("mass", 6.35029318),
    # volume (L)
    "ml": ("volume", 1e-3), "l": ("volume", 1), "m3": ("volume", 1000), "tsp": ("volume", 0.00492892),
    "tbsp": ("volume", 0.0147868), "cup": ("volume", 0.236588), "floz": ("volume", 0.0295735),
    "pt": ("volume", 0.473176), "qt": ("volume", 0.946353), "gal": ("volume", 3.785411784),
    # time (s)
    "ms": ("time", 1e-3), "s": ("time", 1), "min": ("time", 60), "h": ("time", 3600),
    "day": ("time", 86400), "week": ("time", 604800), "year": ("time", 31557600),
    # speed (m/s)
    "m/s": ("speed", 1), "km/h": ("speed", 1 / 3.6), "mph": ("speed", 0.44704), "knot": ("speed", 0.514444),
    # area (m2)
    "m2": ("area", 1), "km2": ("area", 1e6), "ft2": ("area", 0.09290304), "acre": ("area", 4046.8564224),
    "ha": ("area", 1e4),
    # data (bytes)
    "b": ("data", 1), "kb": ("data", 1e3), "mb": ("data", 1e6), "gb": ("data", 1e9), "tb": ("data", 1e12),
    "kib": ("data", 1024), "mib": ("data", 1024 ** 2), "gib": ("data", 1024 ** 3), "tib": ("data", 1024 ** 4),
    # energy (J)
    "j": ("energy", 1), "kj": ("energy", 1e3), "cal": ("energy", 4.184), "kcal": ("energy", 4184),
    "wh": ("energy", 3600), "kwh": ("energy", 3.6e6),
    # pressure (Pa)
    "pa": ("pressure", 1), "kpa": ("pressure", 1e3), "bar": ("pressure", 1e5), "psi": ("pressure", 6894.757),
    "atm": ("pressure", 101325),
}
TEMPS = {"c", "f", "k"}


def convert_units(value: float, from_unit: str, to_unit: str) -> float:
    a, b = from_unit.lower(), to_unit.lower()
    if a in TEMPS and b in TEMPS:
        k = {"c": value + 273.15, "f": (value - 32) * 5 / 9 + 273.15, "k": value}[a]
        return {"c": k - 273.15, "f": (k - 273.15) * 9 / 5 + 32, "k": k}[b]
    if a not in UNITS or b not in UNITS:
        bad = a if a not in UNITS else b
        raise ToolError(f"Unknown unit '{bad}'. Known: {', '.join(sorted(UNITS))}, c, f, k")
    if UNITS[a][0] != UNITS[b][0]:
        raise ToolError(f"Can't convert {UNITS[a][0]} to {UNITS[b][0]}.")
    return value * UNITS[a][1] / UNITS[b][1]


def _zone(name: str | None):
    if not name:
        return dt.datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ToolError(f"Unknown timezone '{name}'. Use IANA names like 'Europe/London', 'America/New_York', 'UTC'.")


def _parse_dt(s: str) -> dt.datetime:
    if s.lower() in {"now", "today"}:
        return dt.datetime.now().astimezone()
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        raise ToolError(f"Can't parse date '{s}'. Use ISO format like 2026-03-01 or 2026-03-01T14:30.")


def register(reg: ToolRegistry) -> None:
    m = lambda *a, **k: reg.tool(*a, category="math", **k)  # noqa: E731
    tt = lambda *a, **k: reg.tool(*a, category="time", **k)  # noqa: E731

    @m("calculator", "Evaluate an arithmetic expression exactly, e.g. '(3.5*12)**2 / sqrt(7)'. "
       "Functions: sqrt sin cos tan log log10 exp floor ceil factorial gcd comb ... "
       "Use this instead of doing maths in your head.",
       S(expression="string"))
    def calculator(ctx: ToolContext, expression: str):
        return str(safe_eval(expression))

    @m("statistics", "Descriptive statistics for a list of numbers: count, sum, mean, median, "
       "mode, stdev, variance, min, max, quartiles.",
       S(numbers={"type": "array", "items": {"type": "number"}}))
    def statistics(ctx: ToolContext, numbers: list):
        xs = [float(x) for x in numbers]
        if not xs:
            raise ToolError("Give at least one number.")
        out = {"count": len(xs), "sum": sum(xs), "mean": st.fmean(xs), "median": st.median(xs),
               "min": min(xs), "max": max(xs)}
        if len(xs) > 1:
            out.update(stdev=st.stdev(xs), variance=st.variance(xs),
                       quartiles=st.quantiles(xs, n=4), mode=st.mode(xs))
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in out.items()}

    @m("unit_convert", "Convert units: length, mass, volume, time, speed, area, data, energy, "
       "pressure, temperature (c/f/k). E.g. value=5, from_unit='mi', to_unit='km'.",
       S(value="number", from_unit="string", to_unit="string"))
    def unit_convert(ctx: ToolContext, value: float, from_unit: str, to_unit: str):
        return f"{value:g} {from_unit} = {convert_units(value, from_unit, to_unit):.6g} {to_unit}"

    @m("convert_base", "Convert an integer between bases 2-36 (e.g. hex 'ff' to binary).",
       S(number="string", from_base="integer", to_base="integer"))
    def convert_base(ctx: ToolContext, number: str, from_base: int, to_base: int):
        if not (2 <= from_base <= 36 and 2 <= to_base <= 36):
            raise ToolError("Bases must be between 2 and 36.")
        try:
            n = int(number.strip().lower().removeprefix("0x").removeprefix("0b").removeprefix("0o"), from_base)
        except ValueError:
            raise ToolError(f"'{number}' is not a valid base-{from_base} number.")
        digits, sign, n = "0123456789abcdefghijklmnopqrstuvwxyz", "-" if n < 0 else "", abs(n)
        out = ""
        while True:
            n, r = divmod(n, to_base)
            out = digits[r] + out
            if n == 0:
                return sign + out

    @tt("current_time", "Get the current date and time (local, or in a given IANA timezone).",
        S(timezone="string?|e.g. 'Asia/Tokyo'; default local"))
    def current_time(ctx: ToolContext, timezone: str | None = None):
        now = dt.datetime.now(_zone(timezone))
        return now.strftime("%A %Y-%m-%d %H:%M:%S %Z (UTC%z)")

    @tt("date_calc", "Date arithmetic: difference between two dates, or add/subtract days/weeks/hours "
        "to a date. Dates in ISO format, or 'today'.",
        S(start="string", end="string?|For a difference",
          add_days="number?", add_weeks="number?", add_hours="number?"))
    def date_calc(ctx: ToolContext, start: str, end: str | None = None, add_days: float = 0,
                  add_weeks: float = 0, add_hours: float = 0):
        a = _parse_dt(start)
        if end:
            b = _parse_dt(end)
            if (a.tzinfo is None) != (b.tzinfo is None):
                a, b = a.replace(tzinfo=None), b.replace(tzinfo=None)
            d = b - a
            weekdays = sum(1 for i in range(abs(d.days))
                           if (min(a, b) + dt.timedelta(days=i)).weekday() < 5)
            return {"days": d.days, "total_hours": round(d.total_seconds() / 3600, 2),
                    "weeks": round(d.days / 7, 2), "weekdays_between": weekdays}
        r = a + dt.timedelta(days=add_days, weeks=add_weeks, hours=add_hours)
        return r.strftime("%A %Y-%m-%d %H:%M") if (add_hours or "T" in start) else r.strftime("%A %Y-%m-%d")

    @tt("convert_timezone", "Convert a date-time from one timezone to another.",
        S(datetime="string|ISO date-time, e.g. 2026-03-01T09:00", from_tz="string", to_tz="string"))
    def convert_timezone(ctx: ToolContext, datetime: str, from_tz: str, to_tz: str):
        d = _parse_dt(datetime).replace(tzinfo=_zone(from_tz))
        return d.astimezone(_zone(to_tz)).strftime("%A %Y-%m-%d %H:%M %Z (UTC%z)")
