"""[RUNTIME] The local model engine kept inside the portable home folder: ollama.py."""
from .ollama import MODELS, OllamaRuntime, recommend_model, total_ram_gb

__all__ = ["MODELS", "OllamaRuntime", "recommend_model", "total_ram_gb"]
