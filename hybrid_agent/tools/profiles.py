"""[TOOLS / profiles] Named tool selections.

Why profiles exist: every tool's name + description + schema is sent to the
model on every request. With ~80 tools that's several thousand tokens - fine
for Claude, but it would eat most of a small local model's 8k context and
confuse it with choice. Profiles hand each agent only what it needs.

Analogy: a toolbox vs. the whole hardware store. A plumber is sent with a
plumber's toolbox, not the entire store.

Profile string syntax (used by AGENT_TOOL_PROFILE, --tools, council configs):
    "core"                       a named profile
    "core,+weather,+git_status"  add individual tools
    "core,@knowledge"            add a whole category
    "full,-run_shell,-delete_path"  remove tools
    "readonly"                   curated look-don't-touch kit
    "readonly_all"               every tool that can't write or execute
"""
from __future__ import annotations

from .registry import ToolRegistry

PROFILES: dict[str, dict] = {
    # Smallest useful set - for 3B-class models.
    "minimal": {"names": ["read_file", "write_file", "edit_file", "list_dir", "calculator",
                          "current_time", "think"]},
    # Default for local models: general-purpose, ~20 tools.
    "core": {"names": ["read_file", "write_file", "edit_file", "append_file", "list_dir", "find_files",
                       "search_text", "run_shell", "run_python", "fetch_url", "web_search", "remember",
                       "recall", "update_plan", "calculator", "current_time", "date_calc", "unit_convert",
                       "think"]},
    # Curated role kits (~15-22 tools each, small enough for local models).
    "research": {"names": ["web_search", "fetch_url", "extract_links", "wikipedia_search",
                           "wikipedia_summary", "arxiv_search", "define_word", "read_feed", "weather",
                           "index_documents", "search_documents", "read_file", "list_dir", "find_files",
                           "write_file", "append_file", "remember", "recall", "text_stats",
                           "extract_entities", "calculator", "current_time", "think"]},
    "coding": {"names": ["read_file", "write_file", "edit_file", "append_file", "list_dir", "tree",
                         "find_files", "search_text", "diff_files", "code_outline", "check_syntax",
                         "run_tests", "run_shell", "run_python", "which", "git_status", "git_diff",
                         "git_log", "regex_find", "web_search", "fetch_url", "think", "update_plan"]},
    "data": {"names": ["csv_read", "csv_query", "json_query", "convert_data", "sqlite_query", "xml_query",
                       "calculator", "statistics", "unit_convert", "run_python", "read_file", "write_file",
                       "list_dir", "find_files", "date_calc", "think"]},
    # Look but don't touch: reading, lookups, maths. Good for reviewers/critics/chairs.
    "readonly": {"names": ["read_file", "list_dir", "find_files", "search_text", "file_info",
                           "code_outline", "csv_read", "json_query", "fetch_url", "web_search",
                           "wikipedia_search", "wikipedia_summary", "recall", "search_documents",
                           "calculator", "statistics", "current_time", "date_calc", "think"]},
    # Broad selections (best with Claude or large local models).
    "readonly_all": {"max_risk": "network"},          # everything that can't write or execute
    "full": {"exclude_categories": ["council"]},      # everything (board tools added in councils)
}


def apply_profile(base: ToolRegistry, spec: str, **subset_kw) -> ToolRegistry:
    """Build a filtered registry from a profile string (see module docstring)."""
    tokens = [t.strip() for t in spec.split(",") if t.strip()] or ["core"]
    name, mods = tokens[0], tokens[1:]
    if name not in PROFILES:
        raise ValueError(f"unknown tool profile '{name}'. Known: {', '.join(PROFILES)}")
    p = PROFILES[name]
    exclude_cats = p.get("exclude_categories", [])
    if "names" in p or "categories" in p:
        reg = base.subset(names=p.get("names"), categories=p.get("categories"),
                          max_risk=p.get("max_risk"), **subset_kw)
    else:
        reg = base.subset(max_risk=p.get("max_risk"), **subset_kw)
    for cat in exclude_cats:
        for n in list(reg.names()):
            if reg.get(n).category == cat:
                reg.unregister(n)
    for m in mods:
        if m.startswith("+"):
            tool = base.get(m[1:])
            if tool is None:
                raise ValueError(f"unknown tool '{m[1:]}' in profile '{spec}'")
            reg._tools[tool.name] = tool
        elif m.startswith("-"):
            reg.unregister(m[1:])
        elif m.startswith("@"):
            found = [t for t in base._tools.values() if t.category == m[1:]]
            if not found:
                raise ValueError(f"unknown category '{m[1:]}' in profile '{spec}'")
            for tool in found:
                reg._tools[tool.name] = tool
        else:
            raise ValueError(f"bad profile token '{m}' (use +tool, -tool or @category)")
    return reg
