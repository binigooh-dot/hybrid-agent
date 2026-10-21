"""hybrid_agent - a tool-using agent that runs on a local model (no API key)
and can optionally use Claude as its primary brain."""
from .agent import Agent
from .config import Config

__all__ = ["Agent", "Config"]
__version__ = "0.1.0"
