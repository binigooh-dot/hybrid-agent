"""[CORE / config] Configuration, read from environment variables (and an optional .env file).

Every setting has a default that works with NO API key: out of the box the
agent talks to a local Ollama server. See `.env.example` for the full list.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: str | os.PathLike = ".env") -> None:
    """Tiny .env loader (KEY=VALUE lines) so we need no third-party package.

    Existing environment variables win over values in the file.
    """
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value[:1] in {'"', "'"}:
            value = value[1:].split(value[0], 1)[0]   # quoted: keep '#' inside quotes
        else:
            value = value.split(" #", 1)[0].strip()   # unquoted: drop inline comment
        os.environ.setdefault(key.strip(), value)


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    # Which brain to use: "auto" (Claude if credentials exist, else local),
    # "claude", "local", or "scripted" (canned replies, for tests/demos).
    backend: str = "auto"

    # --- Claude (optional; needs credentials) ---
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "medium"        # low | medium | high | xhigh | max
    claude_max_tokens: int = 16000
    claude_fallbacks: bool = True        # server-side refusal fallback

    # --- Local model (mandatory for key-free operation) ---
    local_provider: str = "ollama"       # "ollama" or "openai" (llama.cpp, LM Studio, vLLM...)
    local_base_url: str = "http://localhost:11434"
    local_model: str = "qwen2.5:7b"
    local_tool_mode: str = "auto"        # auto | native | prompt
    local_timeout: float = 300.0
    local_num_ctx: int = 8192

    # --- Agent behaviour ---
    workspace: Path = field(default_factory=lambda: Path("workspace"))
    max_steps: int = 25
    auto_approve: bool = False           # skip y/N prompts for risky tools
    max_tool_output: int = 20000         # chars returned to the model per tool call
    shell_timeout: int = 60
    log_dir: Path | None = field(default_factory=lambda: Path("logs"))   # None = no logs
    searxng_url: str | None = None       # optional self-hosted search, no key
    allow_private_network: bool = False  # let web tools reach your LAN / this computer
    # --- Hard safety (see docs/07) ---
    sandbox: str = "auto"                # auto | strict | limits | off - isolation for commands
    require_sandbox: bool = False        # refuse to run commands without strict isolation
    safe_mode: bool = False              # read-only agents: no write or execute tools at all
    min_free_mb: int = 1024              # refuse writes when free disk drops below this
    # Which tools the agent gets (see tools/profiles.py). "auto" = "full" when
    # Claude is the main model, "core" for local models (smaller context).
    tool_profile: str = "auto"

    # --- Council (multi-agent) ---
    council_config: Path | None = None   # JSON file describing members
    council_workers: int = 1             # members run in parallel threads (1 = one at a time)
    persona_dir: Path = field(default_factory=lambda: Path("personas"))  # your persona JSON files

    def context_chars(self) -> int:
        """History budget for local models: ~60% of the context window, ~4 chars per token
        (the rest is left for tool descriptions and the reply)."""
        return int(self.local_num_ctx * 4 * 0.6)

    def validate(self) -> "Config":
        """Fail early, with a clear message, on settings that can't work."""
        choices = {"backend": {"auto", "claude", "local", "scripted"}, "local_provider": {"ollama", "openai"},
                   "local_tool_mode": {"auto", "native", "prompt"},
                   "claude_effort": {"low", "medium", "high", "xhigh", "max"},
                   "sandbox": {"auto", "strict", "limits", "off"}}
        for attr, allowed in choices.items():
            if getattr(self, attr) not in allowed:
                raise ValueError(f"{attr} = {getattr(self, attr)!r}; expected one of {', '.join(sorted(allowed))}")
        positive = ["max_steps", "max_tool_output", "shell_timeout", "local_num_ctx", "council_workers",
                    "claude_max_tokens"]
        for attr in positive:
            if getattr(self, attr) <= 0:
                raise ValueError(f"{attr} must be positive (got {getattr(self, attr)})")
        if not self.local_base_url.startswith(("http://", "https://")):
            raise ValueError(f"LOCAL_BASE_URL must start with http:// or https:// (got {self.local_base_url!r})")
        return self

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        e = os.environ.get
        return cls(
            backend=e("AGENT_BACKEND", "auto"),
            claude_model=e("CLAUDE_MODEL", "claude-opus-5-5"),
            claude_effort=e("CLAUDE_EFFORT", "medium"),
            claude_max_tokens=int(e("CLAUDE_MAX_TOKENS", "16000")),
            claude_fallbacks=_bool("CLAUDE_FALLBACKS", True),
            local_provider=e("LOCAL_PROVIDER", "ollama"),
            local_base_url=e("LOCAL_BASE_URL", "http://localhost:11434"),
            local_model=e("LOCAL_MODEL", "qwen2.5:7b"),
            local_tool_mode=e("LOCAL_TOOL_MODE", "auto"),
            local_timeout=float(e("LOCAL_TIMEOUT", "300")),
            local_num_ctx=int(e("LOCAL_NUM_CTX", "8192")),
            workspace=Path(e("AGENT_WORKSPACE", "workspace")),
            max_steps=int(e("AGENT_MAX_STEPS", "25")),
            auto_approve=_bool("AGENT_AUTO_APPROVE", False),
            max_tool_output=int(e("AGENT_MAX_TOOL_OUTPUT", "20000")),
            shell_timeout=int(e("AGENT_SHELL_TIMEOUT", "60")),
            log_dir=Path(e("AGENT_LOG_DIR", "logs")),
            searxng_url=e("SEARXNG_URL") or None,
            allow_private_network=_bool("AGENT_ALLOW_PRIVATE_NETWORK", False),
            sandbox=e("AGENT_SANDBOX", "auto"),
            require_sandbox=_bool("AGENT_REQUIRE_SANDBOX", False),
            safe_mode=_bool("AGENT_SAFE_MODE", False),
            min_free_mb=int(e("AGENT_MIN_FREE_MB", "1024")),
            tool_profile=e("AGENT_TOOL_PROFILE", "auto"),
            council_config=Path(e("COUNCIL_CONFIG", "")) if e("COUNCIL_CONFIG") else None,
            council_workers=int(e("COUNCIL_WORKERS", "1")),
            persona_dir=Path(e("AGENT_PERSONA_DIR", "personas")),
        )


def claude_credentials_present() -> bool:
    """True if an Anthropic credential is visible in the environment.

    The SDK can also use an `ant auth login` profile; set AGENT_BACKEND=claude
    explicitly if you rely on that, since we can't cheaply detect it here.
    """
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
