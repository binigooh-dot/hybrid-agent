"""[RUNTIME] The local model engine kept inside the portable home folder: ollama.py."""
from .ollama import MODELS, OllamaRuntime

__all__ = ["MODELS", "OllamaRuntime"]
