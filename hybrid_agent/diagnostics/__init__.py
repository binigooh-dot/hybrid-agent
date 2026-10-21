"""[DIAGNOSTICS] Safety drills (simulated critical events) and integrity checks.

    python -m hybrid_agent diagnose            # run everything, print a report
    python -m hybrid_agent diagnose --json     # machine-readable

drills.py     simulated attacks/failures, each in a throwaway sandbox
integrity.py  code-integrity checks (schemas, profiles, labels, compile)
runner.py     runs both with per-drill timeouts and safety harnesses
"""
