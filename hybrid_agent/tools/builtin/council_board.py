"""[TOOLS / council] Shared blackboard tools for council members.

Tools: board_post, board_read

Only useful when the ToolContext has a `blackboard` (the Council sets one up).
Analogy: a whiteboard in the meeting room. Any member can pin a finding,
question or draft to it, and every other member can read it, while each
member still keeps their own private notes (their conversation history).
"""
from __future__ import annotations

from ..registry import S, ToolContext, ToolError, ToolRegistry

CATEGORY = "council"


def register(reg: ToolRegistry) -> None:
    t = reg.group(CATEGORY)

    @t("board_post", "Post a note to the council's shared board so other members can see it "
       "(findings, evidence, open questions, drafts).",
       S(content="string", topic="string?|Short label, e.g. 'evidence' or 'question'"))
    def board_post(ctx: ToolContext, content: str, topic: str = "note"):
        if ctx.blackboard is None:
            raise ToolError("No shared board: you are not in a council session.")
        entry = ctx.blackboard.post(ctx.agent_name, content, topic)
        return f"Posted as #{entry['id']}."

    @t("board_read", "Read the council's shared board (optionally only one topic or recent posts).",
       S(topic="string?", last="integer?|Only the most recent N posts"))
    def board_read(ctx: ToolContext, topic: str | None = None, last: int | None = None):
        if ctx.blackboard is None:
            raise ToolError("No shared board: you are not in a council session.")
        return ctx.blackboard.render(topic=topic, last=last)
