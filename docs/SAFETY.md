# Safety

The agents run on your computer, so several independent safety layers sit between them and anything that
matters. If one layer misses something, the next one catches it, like the layered locks on a bank vault.

```
 agent wants to act
   |
   +-- 1. Is the tool allowed? ---------- look-only tasks and safe mode have no write/run tools
   +-- 2. Is the path inside workspace? -- everything else is refused
   +-- 3. Is it a protected file? -------- system files, your keys, the app itself: refused
   +-- 4. Is it risky? ------------------- run / delete / overwrite / download: asks YOU (3 min, then no)
   +-- 5. Back up first ------------------- every change or delete can be undone
   +-- 6. Run it in a box ----------------- time limits; no API keys; strict sandbox where available
   +-- 7. Write it down ------------------- audit log in home\logs\audit.jsonl
```

## What is on by default

| Layer | What it does |
|---|---|
| Workspace fence | File tools only work inside `home\workspace`. Paths that try to escape (`..\`, links) are refused. |
| Approvals | Running commands or code, deleting, overwriting, moving and downloading wait for your **Allow**. Silence means **Deny**. |
| Undo history | Before any overwrite, edit, move or delete, a copy is saved. **Settings > Undo history > Restore** puts it back. |
| Protected files | System folders, devices, your SSH/cloud keys and the app's own files can't be targeted, even by a command. |
| Command limits | Commands get a time limit and never see secret-looking settings such as API keys. On Linux they also run in a strict sandbox (bubblewrap) where only the workspace is writable; on Windows there is no such sandbox, so approvals are the main guard. |
| Disk guard | Writing stops before your free disk space drops below 1 GB. |
| Web manners | Agents can reach the public internet, not your home network or this computer. They identify honestly and respect rate limits. |
| Look-only tasks | Scheduled tasks can read and browse but not change anything, unless you pick "Ask me first". |
| Private app | The app listens on `127.0.0.1` only, with a new secret link each launch. Other devices can't connect. |
| Integrity check | The download includes a fingerprint of every program file; **Settings > Run safety drills** spots changes. |

## Extra caution (optional)

- **Safe mode** (Settings): agents can only look, never change or run anything.
- `AGENT_REQUIRE_SANDBOX=1` in `home\settings.env`: refuse to run commands unless the strict sandbox is available.

## Things to avoid

- `AGENT_AUTO_APPROVE=1` turns off the questions. Only use it for throwaway experiments.
- Don't put files you can't lose in `home\workspace` without a backup elsewhere. The undo history helps,
  but it is not a backup system.

## Checking it yourself

**Settings > Run safety drills** runs 39 fire drills. Each one simulates an attack or accident (deleting
system files, escaping the workspace, filling the disk, a runaway command...) in a throwaway folder and
checks that it was stopped. Nothing destructive runs for real.
