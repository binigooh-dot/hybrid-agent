"""[BACKENDS / interface] The interface every model backend implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..core.errors import BackendUnavailable
from ..core.messages import LLMResponse, Message

__all__ = ["Backend", "BackendUnavailable"]  # BackendUnavailable re-exported for backend authors


class Backend(ABC):
    name: str = "base"
    model: str = ""
    # May the agent shorten old tool results to fit the context window?
    # True for local models. False for Claude: its API requires the history to
    # be sent back unedited (thinking blocks are bound to it).
    allows_history_trim: bool = False

    @abstractmethod
    def chat(
        self,
        system: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send the conversation, return the model's next turn.

        `tools` is a list of neutral tool specs:
            {"name": str, "description": str, "parameters": <JSON schema>}
        """

    def describe(self) -> str:
        return f"{self.name}:{self.model}"
