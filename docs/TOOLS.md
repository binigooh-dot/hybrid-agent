# Tool reference

No tool needs an API key. ⚠ marks tools that ask for y/N approval (skip the prompt with `-y`).

| Group | Tool | What it does | Notes |
|---|---|---|---|
| Files | `read_file` | Read a file with line numbers (`offset`, `limit`) | Workspace only |
| | `write_file` | Create or overwrite a file | ⚠ asks before **overwriting** |
| | `edit_file` | Replace an exact snippet | Fails if the snippet is missing or ambiguous, so edits are never silent |
| | `list_dir` | List one folder | |
| | `find_files` | Glob search (`*.py`, `src/**/*.md`) | Skips `.git`, `node_modules`, venvs |
| | `search_text` | Regex search through file contents | Up to 200 matches |
| Execution | `run_shell` ⚠ | Run a shell command in the workspace | Timeout (`AGENT_SHELL_TIMEOUT`); destructive commands blocked |
| | `run_python` ⚠ | Run a Python snippet in a fresh interpreter | Same timeout |
| Web | `fetch_url` | Download a page and convert it to plain text | http/https only, 2 MB cap |
| | `web_search` | Search the web | SearXNG if `SEARXNG_URL` is set, else DuckDuckGo HTML |
| Memory | `remember` / `recall` / `forget` | Persistent key → note store | `<workspace>/.agent/memory.json` |
| Planning | `update_plan` | Keep a checklist for multi-step tasks | Shows `[ ]`, `[~]`, `[x]` |
| Utility | `calculator` | Exact arithmetic + math functions | Parses the expression safely; never calls `eval()` |
| | `current_time` | Local date, time and timezone | |
| Hybrid | `delegate_to_local` | Claude sends a simple text job to the free local model | Only registered when Claude is the main model |

## Safety model

```
model asks for tool ──► schema validation ──► approval (⚠ tools) ──► safety checks ──► run ──► truncate output
                          │ bad args → error       │ "no" → error        │ path outside workspace → error
                          ▼                        ▼                     │ blocked shell command → error
                       model retries          model told the user declined
```

The workspace fence protects files, but **`run_shell` and `run_python` can still reach
anything your user account can.** The blocklist only catches obvious disasters. For real
isolation, run the agent in a container or VM, or leave `-y` off and read each command.

## Adding a tool

```python
from hybrid_agent.tools.registry import ToolError

@registry.tool(
    "word_count",                                   # name the model will use
    "Count the words in a workspace text file.",    # the model reads this, so be specific
    {"type": "object",
     "properties": {"path": {"type": "string"}},
     "required": ["path"]},
    requires_approval=False,
)
def word_count(ctx, path):
    from hybrid_agent.safety import resolve_in_workspace
    p = resolve_in_workspace(ctx.workspace, path)    # always use this for paths
    if not p.exists():
        raise ToolError(f"No such file: {path}")      # ToolError → message the model sees
    return str(len(p.read_text().split()))           # return str, or anything JSON-serialisable
```

Tips for tools that small local models can use reliably:
- Keep argument names obvious and few, and mark the ones that matter as `required`.
- Write error messages that say how to fix the call ("re-read the file and copy the text exactly").
- Return short output. Everything is truncated to `AGENT_MAX_TOOL_OUTPUT` characters anyway.
