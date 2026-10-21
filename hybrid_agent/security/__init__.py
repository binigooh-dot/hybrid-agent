"""[SECURITY] Every protective layer in one place.

    guards.py        workspace fence, unsafe-workspace refusal, shell blocklist,
                     size-limited reads, ReDoS-safe regex
    netguard.py      which network addresses tools may contact (+ redirect checks)
    redact.py        scrub secrets from logs, transcripts and GUI events
    xmlsafe.py       parse untrusted XML without entity tricks
    regex_worker.py  child process that runs risky regexes (killable on timeout)

The safety drills in diagnostics/ prove each of these holds.
"""
