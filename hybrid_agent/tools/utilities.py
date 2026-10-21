"""Small utility tools: planning (todo list), safe calculator, clock, delegation."""
from __future__ import annotations

import ast
import datetime as dt
import math
import operator

from .registry import ToolContext, ToolError, ToolRegistry

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_FUNCS = {name: getattr(math, name) for name in
          ("sqrt", "sin", "cos", "tan", "log", "log10", "log2", "exp", "floor", "ceil",
           "factorial", "radians", "degrees")}
_FUNCS.update(abs=abs, round=round, min=min, max=max)
_CONSTS = {"pi": math.pi, "e": math.e}


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
        return ev(ast.parse(expr, mode="eval"))
    except SyntaxError as e:
        raise ToolError(f"Syntax error: {e.msg}")
    except ZeroDivisionError:
        raise ToolError("Division by zero.")


def register(reg: ToolRegistry) -> None:

    @reg.tool("calculator",
              "Evaluate an arithmetic expression exactly, e.g. '(3.5*12)**2 / sqrt(7)'. "
              "Use this instead of doing maths in your head.",
              {"type": "object", "properties": {"expression": {"type": "string"}},
               "required": ["expression"]})
    def calculator(ctx: ToolContext, expression: str):
        return str(safe_eval(expression))

    @reg.tool("current_time", "Get the current local date and time.",
              {"type": "object", "properties": {}, "required": []})
    def current_time(ctx: ToolContext):
        now = dt.datetime.now().astimezone()
        return now.strftime("%A %Y-%m-%d %H:%M:%S %Z (UTC%z)")

    @reg.tool("update_plan",
              "Write the full task plan (replaces the old one). Use for multi-step work; "
              "mark each item pending, in_progress or done as you go.",
              {"type": "object", "properties": {"items": {"type": "array", "items": {
                  "type": "object", "properties": {
                      "task": {"type": "string"},
                      "status": {"type": "string", "enum": ["pending", "in_progress", "done"]}},
                  "required": ["task", "status"]}}},
               "required": ["items"]})
    def update_plan(ctx: ToolContext, items: list):
        for it in items:
            if not isinstance(it, dict) or "task" not in it:
                raise ToolError("Each item needs 'task' and 'status'.")
        ctx.state["plan"] = items
        marks = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]"}
        return "\n".join(f"{marks.get(i.get('status'), '[ ]')} {i['task']}" for i in items)

    @reg.tool("delegate_to_local",
              "Hand a self-contained text task (summarise, translate, draft, classify) to the "
              "free local model and get its answer back. Saves Claude usage on simple work.",
              {"type": "object", "properties": {
                  "task": {"type": "string", "description": "Complete instructions + any input text"}},
               "required": ["task"]})
    def delegate_to_local(ctx: ToolContext, task: str):
        if ctx.local_backend is None:
            raise ToolError("No local model configured.")
        return ctx.local_backend.complete(task)
