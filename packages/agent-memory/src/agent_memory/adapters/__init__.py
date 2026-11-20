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
6. **Say who did it.** Every event carries the agent and a writer id (`<agent>:<session>`), and a file change
   that an agent's tool or command explains names that writer (`by`), so agents sharing a project stay apart.

Adapters: `claude_code` (Stage 3.1, hooks) and `opencode` (Stage 3.3, an in-process plugin).

Entry points:
- `amem hook <agent> <event>` reads the agent's JSON on stdin and prints the agent's hook output;
- `amem mcp` serves the tools, and starts the session server beside them;
- `amem serve` runs the session server alone, for agents whose plugins run in-process.

**Fast path (#90).** A hook first offers its payload to the project's session server (`server.py`), which has the
store open already. With no server, or a failed hand-off, it runs `amem hook` directly; idempotency keys make
that retry safe.
"""
from __future__ import annotations

import hashlib
import json

from agent_memory.schema import canonical_json

AGENTS = ("claude-code", "opencode")
ADAPTER_VERSION = "0.1.0"


def idempotency(agent: str, event: str, payload: dict, part: str = "") -> str:
    """A stable key for one agent payload (and part of it): replays dedupe."""
    digest = hashlib.sha256(canonical_json({"agent": agent, "event": event, "part": part,
                                            "payload": payload}).encode()).hexdigest()
    return f"{agent}:{digest[:40]}"


def run(agent: str, event: str, stdin: bytes, environ: dict, store=None) -> tuple[str, int]:
    """Run one hook. Returns (stdout, exit code); the exit code is always 0.

    `store` is an already open store (the session server's, #90); without one the adapter opens its own.
    """
    if agent == "claude-code":
        from agent_memory.adapters import claude_code
        return claude_code.handle(event, stdin, environ, store=store)
    if agent == "opencode":
        from agent_memory.adapters import opencode
        return opencode.handle(event, stdin, environ, store=store)
    return "", 0


__all__ = ["AGENTS", "ADAPTER_VERSION", "idempotency", "run", "json"]
