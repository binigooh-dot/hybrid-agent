"""[TOOLS / agent] Tools that help the agent organise its own work.

Tools: update_plan, think, ask_user, delegate_to_local

`think` is a scratchpad: writing reasoning down as a tool call measurably
helps smaller local models on multi-step tasks, and costs nothing.
"""
from __future__ import annotations

from ..registry import S, ToolContext, ToolError, ToolRegistry

CATEGORY = "agent"


def register(reg: ToolRegistry) -> None:
    t = reg.group(CATEGORY)

    @t("update_plan", "Write the full task plan (replaces the old one). Use for multi-step work; "
       "mark each item pending, in_progress or done as you go.",
       S(items={"type": "array", "items": {
           "type": "object", "properties": {
               "task": {"type": "string"},
               "status": {"type": "string", "enum": ["pending", "in_progress", "done"]}},
           "required": ["task", "status"]}}))
    def update_plan(ctx: ToolContext, items: list):
        for it in items:
            if not isinstance(it, dict) or "task" not in it:
                raise ToolError("Each item needs 'task' and 'status'.")
        ctx.state["plan"] = items
        marks = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]"}
        return "\n".join(f"{marks.get(i.get('status'), '[ ]')} {i['task']}" for i in items)

    @t("think", "Write down your reasoning, a hypothesis, or a check of your work. Nothing is "
       "executed; use it to think step by step before acting.",
       S(thought="string"))
    def think(ctx: ToolContext, thought: str):
        ctx.state.setdefault("thoughts", []).append(thought)
        return "Noted."

    @t("ask_user", "Ask the human a clarifying question and wait for the answer. Only use when "
       "you genuinely can't proceed without it.",
       S(question="string"))
    def ask_user(ctx: ToolContext, question: str):
        return ctx.ask_user(question)

    @t("delegate_to_local", "Hand a self-contained text task (summarise, translate, draft, classify) "
       "to the free local model and get its answer back. Saves Claude usage on simple work.",
       S(task="string|Complete instructions + any input text"))
    def delegate_to_local(ctx: ToolContext, task: str):
        if ctx.local_backend is None:
            raise ToolError("No local model configured.")
        return ctx.local_backend.complete(task)
