"""[BACKENDS / interface] The interface every model backend implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..core.errors import BackendUnavailable  # noqa: F401  (re-exported)
from ..core.messages import LLMResponse, Message


class Backend(ABC):
    name: str = "base"
    model: str = ""

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
