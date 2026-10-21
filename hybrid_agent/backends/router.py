"""[BACKENDS / router] Router: try the primary backend, fall back to the secondary on failure.

Analogy: a phone that prefers Wi-Fi (Claude) but silently switches to
mobile data (local model) when Wi-Fi drops. The call doesn't end.
"""
from __future__ import annotations

import logging

from .base import Backend, BackendUnavailable

log = logging.getLogger(__name__)


class RouterBackend(Backend):
    name = "router"

    def __init__(self, primary: Backend, fallback: Backend | None = None):
        self.primary = primary
        self.fallback = fallback
        self.model = primary.model
        self.last_used: Backend = primary

    def chat(self, system, messages, tools=None):
        try:
            resp = self.primary.chat(system, messages, tools)
            self.last_used = self.primary
            return resp
        except BackendUnavailable as e:
            if self.fallback is None:
                raise
            log.warning("primary backend %s failed (%s); using %s",
                        self.primary.describe(), e, self.fallback.describe())
            resp = self.fallback.chat(system, messages, tools)
            self.last_used = self.fallback
            return resp

    def describe(self) -> str:
        fb = f" -> fallback {self.fallback.describe()}" if self.fallback else ""
        return f"{self.primary.describe()}{fb}"
