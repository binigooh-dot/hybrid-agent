"""[SCRIPTS / docs] Build docs/agent_builder_suite.html, the browsable Agent Builder Knowledge Suite.

    python scripts/gen_knowledge_suite.py           # open the file in any browser, works offline

If logs/diagnostics-latest.json exists (written by `python -m hybrid_agent diagnose`),
the latest drill results are included in the Safety centre.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hybrid_agent.core.config import Config
from hybrid_agent.gui.guide import build_guide_html

if __name__ == "__main__":
    cfg = Config(log_dir=ROOT / "logs", persona_dir=ROOT / "personas")
    out = ROOT / "docs" / "agent_builder_suite.html"
    out.write_text(build_guide_html(cfg=cfg))
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")
