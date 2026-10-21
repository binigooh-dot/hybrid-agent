"""Model backends and the factory that picks one from Config."""
from __future__ import annotations

from ..config import Config, claude_credentials_present
from .base import Backend, BackendUnavailable
from .local import LocalBackend
from .router import RouterBackend
from .scripted import ScriptedBackend, demo_script

__all__ = ["Backend", "BackendUnavailable", "LocalBackend", "RouterBackend",
           "ScriptedBackend", "build_backend", "build_local_backend"]


def build_local_backend(cfg: Config) -> LocalBackend:
    return LocalBackend(model=cfg.local_model, base_url=cfg.local_base_url,
                        provider=cfg.local_provider, tool_mode=cfg.local_tool_mode,
                        timeout=cfg.local_timeout, num_ctx=cfg.local_num_ctx)


def _build_claude(cfg: Config) -> Backend:
    from .claude import ClaudeBackend
    return ClaudeBackend(model=cfg.claude_model, effort=cfg.claude_effort,
                         max_tokens=cfg.claude_max_tokens, fallbacks=cfg.claude_fallbacks)


def build_backend(cfg: Config) -> Backend:
    """
    backend="local"    -> local model only (no key needed)
    backend="claude"   -> Claude, falling back to local if Claude fails
    backend="auto"     -> like "claude" when credentials exist, else "local"
    backend="scripted" -> canned demo replies
    """
    mode = cfg.backend
    if mode == "scripted":
        return demo_script()
    local = build_local_backend(cfg)
    if mode == "local" or (mode == "auto" and not claude_credentials_present()):
        return local
    if mode in {"claude", "auto"}:
        try:
            return RouterBackend(primary=_build_claude(cfg), fallback=local)
        except BackendUnavailable:
            if mode == "claude":
                raise
            return local
    raise ValueError(f"unknown backend {mode!r}")
