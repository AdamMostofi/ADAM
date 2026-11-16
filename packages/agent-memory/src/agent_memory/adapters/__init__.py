"""Agent adapters: the contract between a coding agent and the engine (Stage 3.1).

**The contract.** Every adapter follows these rules:

1. **Translate, don't decide.** Each agent event becomes canonical events (`EventInput`) with an honest `completeness`:
   - `captured`: the agent gave us all of it;
   - `partial`: some of it, and the summary says what's missing;
   - `unavailable`: a gap record, never a silent loss.
2. **Never block the agent.** `run()` returns quickly with output the agent understands, and never raises.
   - If the store is broken, the failure goes to the store's content-free spool and becomes a `capture_gap` when the store next opens.
3. **Replays are free.** Each event's idempotency key is a hash of the agent's payload, so the same payload is stored once.
4. **Deliver context through the engine.** Adapters ask the context manager for what to inject, and pass it through the agent's own mechanism (hook output, a tool result), within the agent's limits.
5. **No content in logs.** Diagnostics name the event and the error, never the payload.

Entry points:
- `amem hook <agent> <event>` reads the agent's JSON on stdin and prints the agent's hook output;
- `amem mcp` serves the tools.
"""
from __future__ import annotations

import hashlib
import json

from agent_memory.schema import canonical_json

AGENTS = ("claude-code",)
ADAPTER_VERSION = "0.1.0"


def idempotency(agent: str, event: str, payload: dict, part: str = "") -> str:
    """A stable key for one agent payload (and part of it): replays dedupe."""
    digest = hashlib.sha256(canonical_json({"agent": agent, "event": event, "part": part,
                                            "payload": payload}).encode()).hexdigest()
    return f"{agent}:{digest[:40]}"


def run(agent: str, event: str, stdin: bytes, environ: dict) -> tuple[str, int]:
    """Run one hook. Returns (stdout, exit code); the exit code is always 0."""
    if agent == "claude-code":
        from agent_memory.adapters import claude_code
        return claude_code.handle(event, stdin, environ)
    return "", 0


__all__ = ["AGENTS", "ADAPTER_VERSION", "idempotency", "run", "json"]
