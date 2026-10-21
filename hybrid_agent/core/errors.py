"""[CORE / errors] Exception types shared across the package.

Kept in one dependency-free module so every layer can import them without
circular imports.
"""


class ToolError(Exception):
    """Raise inside a tool for an expected failure; the message goes to the model."""


class BackendUnavailable(RuntimeError):
    """A model backend can't serve a request right now (no network, no key,
    server down, rate-limited). The router catches this and falls back."""
