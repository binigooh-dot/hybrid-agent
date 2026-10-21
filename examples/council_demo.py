"""[EXAMPLE / library] Build and run a council from Python.

    python examples/council_demo.py           # canned demo replies, no model needed
    python examples/council_demo.py --local   # real local models (needs Ollama)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hybrid_agent.core.config import Config
from hybrid_agent.council import Council, MemberSpec

backend = "local" if "--local" in sys.argv else "scripted"
cfg = Config(backend=backend, workspace=Path("workspace"), log_dir=Path("logs"))

council = Council([
    MemberSpec("chair", role="chair"),
    MemberSpec("analyst", role="analyst"),
    MemberSpec("skeptic", role="skeptic"),
    MemberSpec("advocate", role="advocate", weight=1.5),
], cfg, on_event=lambda kind, d: print(" ", d["event"], d.get("member", ""), d.get("kind", ""))
          if kind == "council" else None)

result = council.deliberate(
    "Which should a small team adopt first for its new web app?",
    protocol="vote", options=["PostgreSQL", "SQLite", "MongoDB"])

print("\nVote:", result.tally["summary"])
print("\n" + result.final_answer)
print("\nTranscript saved to", result.save(cfg.log_dir))
