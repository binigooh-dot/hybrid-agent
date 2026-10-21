"""[EXAMPLE / library] Add your own tool and run the agent from Python.

    python examples/custom_tool.py            # uses the local model (needs Ollama)
    python examples/custom_tool.py --demo     # scripted, no model needed
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hybrid_agent import Agent
from hybrid_agent.backends import LocalBackend, ScriptedBackend
from hybrid_agent.core.messages import Message, ToolCall
from hybrid_agent.tools import S, ToolContext, build_registry

ctx = ToolContext(workspace=Path("workspace"), approver=lambda *a: True)
tools = build_registry(ctx, "minimal")          # start small, then add your own


@tools.tool("shout", "Upper-case some text and add exclamation marks.",
            S(text="string", marks="integer?|How many '!', default 1"), category="text")
def shout(ctx, text, marks=1):
    return text.upper() + "!" * marks


if "--demo" in sys.argv:
    backend = ScriptedBackend([
        Message(role="assistant", tool_calls=[ToolCall("1", "shout", {"text": "hello", "marks": 3})]),
        lambda msgs: Message(role="assistant", content=f"The tool said: {msgs[-1].content}"),
    ])
else:
    backend = LocalBackend("qwen2.5:7b")

agent = Agent(backend, tools)
print(agent.run("Use the shout tool on 'hello' with 3 marks."))
