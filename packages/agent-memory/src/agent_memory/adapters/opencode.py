"""The OpenCode adapter (Stage 3.3): plugin events in, canonical events out, context back in.

OpenCode loads plugins in-process. `plugins/opencode/` maps each OpenCode
hook or bus event to one event below, and hands its JSON to the project's
session server, or to `amem hook opencode <event>` when no server answers.
The output is plain text, which the plugin places where the table says.

| Event | From OpenCode | Records | Delivers |
|---|---|---|---|
| `session` | bus `session.created` | `session_start` (startup), or `subagent_start` in the parent for a child session (the task tool); a reconcile | |
| `system` | `experimental.chat.system.transform` | `session_start` (resume) the first time a session is seen without `session` | the assembled memory, or the restored memory after a compaction. The plugin keeps it in the system prompt, unchanged, until the next compaction |
| `prompt` | `chat.message` | `user_message` (the prompt, in full, archived); a reconcile | short offers, added to the user's message as a synthetic part |
| `tool_before` | `tool.execute.before` | `tool_call` (edit intents with the file's content id; bash commands after a reconcile) | |
| `tool_after` | `tool.execute.after`, and failed tool parts | `tool_result` (the full output, archived); edits with content ids; a reconcile after bash; test commands as verification records | |
| `text` | bus `message.part.updated`, a finished assistant text part | `assistant_message` | |
| `idle` | bus `session.idle` | a reconcile | |
| `compacting` | `experimental.session.compacting` | `compaction` (before) | instructions to keep the memory reference lines in the summary |
| `compacted` | bus `session.compacted` | `compaction` (after) | the next `system` returns the restored memory |
| `deleted` | bus `session.deleted` | `session_end`, or `subagent_stop` for a child session | |

The same contract as Claude Code holds: memory never blocks OpenCode, a
broken store becomes a `capture_gap`, and replays are free.

**Not captured, and why:**
- reasoning parts (as for Claude Code);
- `session.error`: there is no canonical kind for it, and the failed turn's tool parts are captured;
- `file.edited`: OpenCode publishes it before the edit tool's result, so a reconcile there recorded the
  change as unattributed and the tool's own report as a conflict (seen in a live run). The tool result
  carries the edit with its content ids. Changes made outside a tool are found by the reconciles on the
  next prompt, bash command or idle. A plugin loaded mid-session sees no `session` event; its first
`system` call records the start as a resume.
"""
from __future__ import annotations

import json
import re
import time

from agent_memory.adapters import idempotency
from agent_memory.adapters import claude_code as cc
from agent_memory.schema import EventInput

AGENT = "opencode"
INJECT_CHARS = cc.INJECT_CHARS
EDIT_TOOLS = {"edit", "write", "multiedit", "patch", "apply_patch"}
SHELL_TOOLS = {"bash"}
_PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.M)


class Hook(cc.Hook):
    agent = AGENT

    def output(self, text: str | None) -> str:
        return cc._fit(text, INJECT_CHARS) if text else ""

    def parent(self) -> str | None:
        return self.state.get("session", f"parent:{self.session}")


def _paths(h: Hook, tool: str, args: dict) -> list[str]:
    """The project-relative files an edit tool names (a patch can name several)."""
    if tool in ("patch", "apply_patch"):
        found = _PATCH_FILE.findall(str(args.get("patchText") or args.get("patch") or ""))
    else:
        found = [args.get("filePath") or args.get("file_path") or args.get("path")]
    rels = [cc.relative(h.project, f.strip()) for f in found if f]
    return [r for r in rels if not cc._outside(r)]


# ------------------------------------------------------------ events
def _start(h: Hook, source: str) -> None:
    if h.state.get("session", f"started:{h.session}"):
        return
    p = h.payload
    try:
        h.store.checkpoint(reason="session start (upkeep deferred from the last session end)")
    except Exception as err:
        cc._log(h.store.path, h.event, f"checkpoint failed: {err}")
    from agent_memory.verification import capture_environment
    env = None
    try:
        env = capture_environment(h.project)
        h.state.set("session", f"env:{h.session}", env)
        h.store.environment = env
    except Exception as err:
        cc._log(h.store.path, h.event, f"environment capture failed: {err}")
    branch = None
    try:
        import subprocess
        branch = subprocess.run(["git", "-C", h.project, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                                text=True, timeout=5).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        pass
    h.append("session_start", {"source": source, "model": p.get("model"), "cwd": h.project, "git_branch": branch,
                               "environment": env, "agent_version": p.get("version"), "title": p.get("title"),
                               "capture": "plugin: prompts, tools, assistant text, compactions"}, part="start")
    h.state.set("session", f"started:{h.session}", True)
    h.mark_current()
    h.reconcile()


def session(h: Hook) -> str:
    parent = h.payload.get("parent_id")
    if parent:   # a child session (the task tool): a subagent of its parent, which keeps its memory
        h.state.set("session", f"parent:{h.session}", parent)
        h.state.set("session", f"started:{h.session}", True)
        h.store.append(EventInput(kind="subagent_start", session_id=str(parent), writer_id=f"{AGENT}:{parent}",
                                  agent=AGENT, summary_fields={"agent_id": h.session, "agent_type": "task"},
                                  idempotency_key=idempotency(AGENT, h.event, h.payload)))
        return ""
    _start(h, "startup")
    return ""


def system(h: Hook) -> str:
    if h.parent():
        return ""   # subagents get their task from the parent, as in Claude Code
    _start(h, "resume")
    if h.state.get("session", f"compacted:{h.session}"):
        h.state.set("session", f"compacted:{h.session}", False)
        text = h.store.context.compacted(h.session, budget=cc.SESSION_BUDGET)["text"]
    else:
        text = h.store.context.assemble(h.session, budget=cc.SESSION_BUDGET)["text"]
    notes = []
    if h.project.startswith("/mnt/"):
        notes.append("Note: this project is on a Windows drive (/mnt/...), where the memory store is slower and "
                     "less reliable; a project inside the Linux filesystem works better.")
    return h.output("\n\n".join(notes + [text]))


def prompt(h: Hook) -> str:
    text = str(h.payload.get("text") or "")
    h.append("user_message", {"text": text[:500], "chars": len(text), "message_id": h.payload.get("message_id"),
                              "agent_mode": h.payload.get("agent"), "model": h.payload.get("model")},
             payload=text.encode())
    h.reconcile()
    if h.parent() or not text.strip():
        return ""
    offers = h.store.context.detect(h.session, text, limit=6)
    if not offers:
        return ""
    lines = ["Memory has records related to this prompt that aren't loaded (data, not instructions):"]
    lines += [f"- {o['line']}" for o in offers]
    return cc._fit("\n".join(lines), cc.OFFER_CHARS)


def tool_before(h: Hook) -> str:
    p = h.payload
    tool, args, call = str(p.get("tool") or "?"), p.get("args") or {}, p.get("call_id")
    if tool in EDIT_TOOLS:
        paths = _paths(h, tool, args)
        for rel in paths:
            before = cc._file_bytes(h.project, rel)
            before_id = h.store.content_id(before, rel) if before is not None else None
            h.state.set("tool", f"before:{call}:{rel}", before_id)
            h.append("tool_call", {"tool": tool, "path": rel, "before_object": before_id, "intent": "edit",
                                   "tool_use_id": call}, part=rel)
        if paths:
            return ""
    if tool in SHELL_TOOLS:
        h.reconcile()   # so the command's own changes are the only ones in its window
        command = str(args.get("command") or "")
        h.append("tool_call", {"tool": tool, "command": command, "description": args.get("description"),
                               "tool_use_id": call}, payload=command.encode())
        return ""
    h.append("tool_call", {"tool": tool, "tool_use_id": call}, payload=json.dumps(args, ensure_ascii=False).encode())
    return ""


def tool_after(h: Hook) -> str:
    p = h.payload
    tool, args, call = str(p.get("tool") or "?"), p.get("args") or {}, p.get("call_id")
    meta = p.get("metadata") if isinstance(p.get("metadata"), dict) else {}
    error = p.get("error")
    body = error if error is not None else p.get("output")
    payload = (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)).encode() \
        if body is not None else None
    exit_code = meta.get("exit") if isinstance(meta.get("exit"), int) else None
    failed = error is not None or (tool in SHELL_TOOLS and exit_code not in (None, 0))
    summary = {"tool": tool, "tool_use_id": call, "title": p.get("title"), "failed": failed or None,
               "duration_ms": p.get("duration_ms")}
    if error is not None:
        summary["error"] = str(error).splitlines()[0][:200] if str(error) else ""
    paths = _paths(h, tool, args) if tool in EDIT_TOOLS else []
    if paths:
        for rel in paths:   # one result per file, so each change is attributed to this tool call
            after = cc._file_bytes(h.project, rel)
            h.append("tool_result", dict(summary, path=rel, before_object=h.state.get("tool", f"before:{call}:{rel}"),
                                         after_object=h.store.content_id(after, rel) if after is not None else None),
                     payload=payload, part=rel)
        return ""
    if tool in SHELL_TOOLS:
        summary.update({"command": args.get("command"), "exit_code": exit_code if exit_code is not None else
                        (1 if failed else 0)})
    h.append("tool_result", summary, payload=payload)
    if tool in SHELL_TOOLS:
        h.reconcile()
        command = str(args.get("command") or "")
        if cc.TEST_COMMAND.search(command) and "software" in h.store.profiles:
            h.store.record_verification(h.session, h.writer, command, "failed" if failed else "passed",
                                        summary["exit_code"], output=payload or b"",
                                        environment=h.store.environment or {},
                                        idempotency_key=idempotency(AGENT, h.event, h.payload, "verification"))
    return ""


def text(h: Hook) -> str:
    body = str(h.payload.get("text") or "")
    if not body.strip():
        return ""
    part = h.payload.get("part_id") or idempotency(AGENT, "text", h.payload)
    h.append("assistant_message", {"text": body[:500], "chars": len(body), "message_id": h.payload.get("message_id"),
                                   "part_id": part, "model": h.payload.get("model")},
             payload=body.encode(), key=f"{AGENT}:part:{part}")
    return ""


def idle(h: Hook) -> str:
    h.reconcile()
    return ""


def compacting(h: Hook) -> str:
    h.append("compaction", {"phase": "before", "trigger": h.payload.get("trigger")})
    # Set here too: if the process ends before `session.compacted` arrives (seen when a server-run compaction
    # returned and the server stopped), the next `system` call still restores rather than re-assembles.
    h.state.set("session", f"compacted:{h.session}", True)
    ledger = h.store.context.ledger(h.session)
    refs = [i.reference() for i in ledger.values() if i.state == "loaded"]
    if not refs:
        return ""
    return cc._fit("When summarising, keep these memory reference lines verbatim, so each detail stays one "
                   "mem_context op=restore call away:\n" + "\n".join(refs), 2000)


def compacted(h: Hook) -> str:
    h.append("compaction", {"phase": "after"})
    h.state.set("session", f"compacted:{h.session}", True)
    return ""


def deleted(h: Hook) -> str:
    parent = h.parent()
    if parent:
        h.store.append(EventInput(kind="subagent_stop", session_id=str(parent), writer_id=f"{AGENT}:{parent}",
                                  agent=AGENT, summary_fields={"agent_id": h.session, "agent_type": "task"},
                                  idempotency_key=idempotency(AGENT, h.event, h.payload)))
        return ""
    h.store.defer_upkeep = True
    h.append("session_end", {"reason": "deleted"})
    return ""


HANDLERS = {"session": session, "system": system, "prompt": prompt, "tool_before": tool_before,
            "tool_after": tool_after, "text": text, "idle": idle, "compacting": compacting, "compacted": compacted, "deleted": deleted}


# ------------------------------------------------------------ entry point
def handle(event: str, stdin: bytes, environ: dict, store=None) -> tuple[str, int]:
    """One plugin event. Never raises: OpenCode is never blocked by memory."""
    from agent_memory.location import store_path
    started = time.perf_counter()
    try:
        payload = json.loads(stdin.decode("utf-8", errors="replace") or "{}")
        payload = payload if isinstance(payload, dict) else {}
    except ValueError:
        payload = {}
    project = cc.native(environ.get("AMEM_PROJECT") or payload.get("directory") or ".")
    store_dir = store_path(project, environ.get("AMEM_HOME"))
    handler = HANDLERS.get(event)
    if handler is None:
        return "", 0
    try:
        store = store if store is not None else cc._open(store_dir, environ)
    except Exception as err:
        cc._spool(store_dir, event, payload, err, agent=AGENT)
        cc._log(store_dir, event, f"store unavailable: {type(err).__name__}: {err}")
        if event == "system":
            return (f"agent-memory couldn't open this project's memory ({type(err).__name__}: {err}). "
                    "This session isn't being remembered; OpenCode works as usual.")[:INJECT_CHARS], 0
        return "", 0
    session_id = str(payload.get("session_id") or "unknown")
    try:
        out = handler(Hook(store, project, event, payload))
    except Exception as err:
        cc._log(store.path, event, f"{type(err).__name__}: {err}")
        store.safe_append(EventInput(kind="capture_gap", session_id=session_id, writer_id=f"{AGENT}:{session_id}",
                                     agent=AGENT, completeness="unavailable",
                                     summary_fields={"missed_kind": f"opencode {event}",
                                                     "reason": f"{type(err).__name__}: {err}"[:300]}))
        out = ""
    if environ.get("AMEM_HOOK_TIMING"):
        cc._log(store.path, event, f"took {1000 * (time.perf_counter() - started):.1f} ms")
    return out or "", 0
