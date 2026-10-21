"""The interface every model backend implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..messages import LLMResponse, Message


class BackendUnavailable(RuntimeError):
    """Raised when a backend can't serve a request (no network, no key,
    server down, rate-limited). The router catches this and falls back."""


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
