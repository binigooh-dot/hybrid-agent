"""[TESTS / docs] Everything the documentation points to must exist: links, file paths, downloads, settings."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", ROOT / "NOTES.md", ROOT / "RELEASE_NOTES.md", ROOT / ".env.example",
        *sorted((ROOT / "docs").glob("*.md")), *sorted((ROOT / "personas").glob("*.md")),
        *sorted((ROOT / "examples").rglob("*.md"))]
PATHLIKE = re.compile(r"`((?:docs|scripts|hybrid_agent|tests|examples|packaging|personas|\.github)/[^`\s*<>{}]+)`")


class DocLinkTests(unittest.TestCase):
    def test_markdown_links_lead_somewhere(self):
        missing = []
        for d in DOCS:
            for m in re.finditer(r"\]\(([^)\s]+)\)", d.read_text(encoding="utf-8")):
                target = m.group(1).split("#")[0]
                if target and not target.startswith(("http://", "https://", "mailto:")) and not (d.parent / target).exists():
                    missing.append(f"{d.relative_to(ROOT).as_posix()} -> {target}")
        self.assertEqual(missing, [])

    def test_file_paths_mentioned_in_docs_exist(self):
        missing = []
        for d in DOCS:
            for m in PATHLIKE.finditer(d.read_text(encoding="utf-8")):
                target = m.group(1).rstrip(".,):")
                if not (ROOT / target).exists():
                    missing.append(f"{d.relative_to(ROOT).as_posix()} -> {target}")
        self.assertEqual(missing, [])

    def test_guide_links_lead_somewhere(self):
        html = (ROOT / "docs" / "agent_builder_suite.html").read_text(encoding="utf-8")
        missing = [h for h in re.findall(r'href="([^"#][^"]*)"', html)
                   if not h.startswith(("http://", "https://", "mailto:", "data:")) and not (ROOT / "docs" / h).exists()]
        self.assertEqual(missing, [])

    def test_download_names_match_this_version(self):
        """README / release notes name the files the build actually produces for this version."""
        from hybrid_agent import __version__
        for doc in ("README.md", "RELEASE_NOTES.md"):
            names = set(re.findall(r"HybridAgent-(\d+\.\d+\.\d+)-", (ROOT / doc).read_text(encoding="utf-8")))
            self.assertLessEqual(names, {__version__}, f"{doc} mentions downloads for {names - {__version__}}")
        self.assertIn(__version__, (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8").splitlines()[0])

    def test_workflow_uses_files_that_exist(self):
        wf = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
        for path in re.findall(r"python (scripts/[\w./-]+\.py)", wf) + ["RELEASE_NOTES.md", "packaging/HybridAgent.spec"]:
            self.assertTrue((ROOT / path).exists(), path)


if __name__ == "__main__":
    unittest.main()
