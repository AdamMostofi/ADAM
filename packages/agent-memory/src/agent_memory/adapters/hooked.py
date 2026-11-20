"""Adapters for agents with command hooks like Claude Code's (Stage 3.5): Codex, Gemini CLI and Cursor.

**Status: built from each agent's official documentation (read 2026-11-20), not tested against a real
install** (owner's decision on #60: none of the three is installed here). The shared adapter suite runs them
on payloads shaped as those docs describe. See `docs/agents.md` for what each one gets, and what is unverified.

Each agent runs a command per hook with JSON on stdin, much as Claude Code does. This module translates the
agent's event and field names into the shape `claude_code`'s handlers read, runs them as that agent, and
formats the reply the way the agent reads it.

| Codex | Gemini CLI | Cursor | Handler | Context back |
|---|---|---|---|---|
| `SessionStart` | `SessionStart` | `sessionStart` | session start | all three (Cursor: `additional_context`, which its docs say the agent doesn't wait for) |
| `UserPromptSubmit` | `BeforeAgent` | `beforeSubmitPrompt` | prompt | Codex, Gemini (Cursor documents no way to add context here) |
| `PreToolUse` | `BeforeTool` | (none: see below) | tool call | |
| `PostToolUse` | `AfterTool` | `postToolUse`, `postToolUseFailure`, `afterFileEdit` | tool result | |
| `Stop` | `AfterAgent` | `afterAgentResponse`, `stop` | the turn's reply | |
| `PreCompact` / `PostCompact` | `PreCompress` | `preCompact` | compaction | |
| `SubagentStart` / `SubagentStop` | | `subagentStop` | subagents | |
| `SessionEnd` | `SessionEnd` | `sessionEnd` | session end | |

**Known limits, from the docs:**
- **Replies:** Codex's and Gemini's transcript formats aren't documented as stable, so only each turn's final
  reply is captured, marked `partial`.
- **Cursor:**
  - Its permission hooks (`preToolUse`, `beforeShellExecution`, `subagentStart`) block the action when the
    output is invalid. A memory hook must never block or approve anything, so they aren't used.
  - Edits come from `afterFileEdit`, with no "before" content, so conflicts can't be detected for Cursor edits.
- **Gemini CLI tool calls** carry no call id, so a call and its result are paired by tool name and input.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from agent_memory.adapters import claude_code as cc
from agent_memory.schema import EventInput

AGENTS = ("codex", "gemini", "cursor")


def _call_id(payload: dict) -> str:
    """Gemini CLI has no tool call id: before and after carry the same tool name and input."""
    key = json.dumps([payload.get("session_id"), payload.get("tool_name"), payload.get("tool_input")],
                     sort_keys=True, default=str)
    return "call-" + hashlib.sha256(key.encode()).hexdigest()[:16]


# ------------------------------------------------------------ translations: (agent event, payload) -> handler calls
def _codex(event: str, p: dict) -> list[tuple[str, dict]]:
    if event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PreCompact", "SubagentStart",
                 "SubagentStop", "SessionEnd"):
        return [(event, p)]
    if event == "PostCompact":
        return [("PostCompact", p)]
    if event == "Stop":
        return [("Reply", p)]
    return []


def _gemini(event: str, p: dict) -> list[tuple[str, dict]]:
    if event == "SessionStart":
        return [("SessionStart", p)]
    if event == "BeforeAgent":
        return [("UserPromptSubmit", p)]
    if event == "BeforeTool":
        return [("PreToolUse", dict(p, tool_use_id=_call_id(p)))]
    if event == "AfterTool":
        response = p.get("tool_response") if isinstance(p.get("tool_response"), dict) else {}
        q = dict(p, tool_use_id=_call_id(p), tool_response=response.get("llmContent", response))
        if response.get("error"):
            return [("PostToolUseFailure", dict(q, error=str(response.get("error"))))]
        return [("PostToolUse", q)]
    if event == "AfterAgent":
        return [("Reply", dict(p, last_assistant_message=p.get("prompt_response")))]
    if event == "PreCompress":
        return [("PreCompact", p)]
    if event == "SessionEnd":
        return [("SessionEnd", p)]
    return []


def _cursor(event: str, p: dict) -> list[tuple[str, dict]]:
    p = dict(p, session_id=p.get("session_id") or p.get("conversation_id"))
    if event == "sessionStart":
        return [("SessionStart", dict(p, source="startup"))]
    if event == "beforeSubmitPrompt":
        return [("UserPromptSubmit", p)]
    if event == "postToolUse":
        if p.get("tool_name") == "Write":   # recorded from afterFileEdit, which names the file for certain
            return []
        return [("PostToolUse", dict(p, tool_response=p.get("tool_output")))]
    if event == "postToolUseFailure":
        return [("PostToolUseFailure", dict(p, error=p.get("error_message") or p.get("failure_type")))]
    if event == "afterFileEdit":
        return [("PostToolUse", dict(p, tool_name="Write", tool_input={"file_path": p.get("file_path")},
                                     tool_use_id=p.get("generation_id"), tool_response={"edits": p.get("edits")}))]
    if event == "afterAgentResponse":
        return [("Reply", dict(p, last_assistant_message=p.get("text"), complete=True))]
    if event == "stop":
        return [("Idle", p)]
    if event == "preCompact":
        return [("PreCompact", p)]
    if event == "subagentStop":
        return [("SubagentStop", dict(p, agent_type=p.get("subagent_type"), agent_id=p.get("subagent_id"),
                                      last_assistant_message=p.get("summary")))]
    if event == "sessionEnd":
        return [("SessionEnd", p)]
    return []


TRANSLATE = {"codex": _codex, "gemini": _gemini, "cursor": _cursor}
PROJECT_ENV = {"codex": (), "gemini": ("GEMINI_PROJECT_DIR",), "cursor": ("CURSOR_PROJECT_DIR",)}


# ------------------------------------------------------------ handlers the agents share
def _reply(h: cc.Hook) -> str:
    """A turn's final reply. Without a stable transcript, earlier messages of the turn aren't captured."""
    text = h.payload.get("last_assistant_message")
    if text:
        text = str(text)
        complete = bool(h.payload.get("complete"))
        summary = {"text": text[:500], "chars": len(text), "source": h.event}
        if not complete:
            summary["missing"] = "messages before the turn's final reply (this agent's transcript isn't read)"
        h.append("assistant_message", summary, payload=text.encode(),
                 completeness="captured" if complete else "partial", key=f"{h.agent}:reply:{h.session}:"
                 f"{h.payload.get('turn_id') or h.payload.get('generation_id') or cc._digest(text)}")
    h.reconcile()
    return ""


def _idle(h: cc.Hook) -> str:
    h.reconcile()
    return ""


HANDLERS = dict(cc.HANDLERS, Reply=_reply, Idle=_idle)


# ------------------------------------------------------------ replies, in each agent's format
def _output(agent: str, agent_event: str, texts: list[str]) -> str:
    """What the agent reads on stdout. Gemini and Cursor parse stdout as JSON, so they always get JSON."""
    context = "\n\n".join(t for t in texts if t)
    if agent == "codex":   # context is read on SessionStart and UserPromptSubmit only; elsewhere it is ignored
        if context and agent_event in ("SessionStart", "UserPromptSubmit"):
            return json.dumps({"hookSpecificOutput": {"hookEventName": agent_event, "additionalContext": context}})
        return ""
    if agent == "gemini":
        if context and agent_event in ("SessionStart", "BeforeAgent"):
            return json.dumps({"hookSpecificOutput": {"hookEventName": agent_event, "additionalContext": context}})
        return "{}"
    if agent == "cursor":
        if agent_event == "sessionStart" and context:
            return json.dumps({"additional_context": context})
        if agent_event == "beforeSubmitPrompt":
            return json.dumps({"continue": True})
        return "{}"
    return ""


def _context(raw: str) -> str:
    """The context text a Claude Code handler produced (it wraps it in Claude Code's hook JSON)."""
    if not raw:
        return ""
    try:
        return json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError, TypeError):
        return raw


def handle(agent: str, event: str, stdin: bytes, environ: dict, store=None) -> tuple[str, int]:
    """One hook from Codex, Gemini CLI or Cursor. Never raises, always exits 0: memory never blocks the agent."""
    from agent_memory.location import store_path
    started = time.perf_counter()
    try:
        payload = json.loads(stdin.decode("utf-8", errors="replace") or "{}")
        payload = payload if isinstance(payload, dict) else {}
    except ValueError:
        payload = {}
    roots = payload.get("workspace_roots") or []
    project = cc.native(environ.get("AMEM_PROJECT") or next((environ[k] for k in PROJECT_ENV.get(agent, ())
                                                             if environ.get(k)), None)
                        or payload.get("cwd") or (roots[0] if roots else None) or ".")
    calls = TRANSLATE[agent](event, payload) if agent in TRANSLATE else []
    if not calls:
        return _output(agent, event, []), 0
    store_dir = store_path(project, environ.get("AMEM_HOME"))
    try:
        store = store if store is not None else cc._open(store_dir, environ)
    except Exception as err:
        cc._spool(store_dir, event, payload, err, agent=agent)
        cc._log(store_dir, event, f"store unavailable: {type(err).__name__}: {err}")
        note = (f"agent-memory couldn't open this project's memory ({type(err).__name__}: {err}). "
                "This session isn't being remembered; the agent works as usual.")
        return _output(agent, event, [note] if calls[0][0] == "SessionStart" else []), 0

    hook_cls = type(f"{agent}Hook", (cc.Hook,), {"agent": agent})
    texts = []
    for handler_event, p in calls:
        session_id = str(p.get("session_id") or "unknown")
        # These agents' transcripts aren't in Claude Code's format (nor documented as stable): never parse them.
        p = {k: v for k, v in p.items() if k != "transcript_path"}
        try:
            h = hook_cls(store, project, handler_event, dict(p, session_id=session_id))
            h.event = f"{agent} {event}"   # idempotency keys and logs name the agent's own event
            texts.append(_context(HANDLERS[handler_event](h)))
        except Exception as err:
            cc._log(store.path, event, f"{type(err).__name__}: {err}")
            store.safe_append(EventInput(kind="capture_gap", session_id=session_id, writer_id=f"{agent}:{session_id}",
                                         agent=agent, completeness="unavailable",
                                         summary_fields={"missed_kind": f"{agent} {event}",
                                                         "reason": f"{type(err).__name__}: {err}"[:300]}))
    if environ.get("AMEM_HOOK_TIMING"):
        cc._log(store.path, event, f"took {1000 * (time.perf_counter() - started):.1f} ms")
    return _output(agent, event, texts), 0
