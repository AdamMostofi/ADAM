"""The Pi adapter (Stage 3.4): extension events in, canonical events out, context back in.

Pi loads extensions in-process. `plugins/pi/` maps each Pi event to one event
below and hands its JSON to the project's session server, or to
`amem hook pi <event>` when no server answers. The output is plain text, which
the extension places where the table says.

| Event | From Pi | Records | Delivers |
|---|---|---|---|
| `session` | `session_start` (startup, resume, new, fork, reload) | `session_start`: a session seen before is a resume; one whose header names a parent is a fork (`forked_from`), which the core makes an engine branch | |
| `brief` | `before_agent_start` | | the assembled memory, or the restored memory after a compaction or a branch change. The extension keeps it in an `agent_memory` prompt section, unchanged until then |
| `prompt` | `before_agent_start` (user runs) | `user_message` (the prompt, in full); a reconcile | short offers, added to the run as a hidden custom message |
| `tool_before` | `tool_call` | `tool_call` (edit intents with the file's content id; bash commands after a reconcile) | |
| `tool_after` | `tool_result` | `tool_result` (the full output); edits with content ids; a reconcile after bash; test commands as verification records | |
| `text` | `message_end`, assistant messages with text | `assistant_message` | |
| `idle` | `agent_settled` | a reconcile | |
| `compacting` | `session_before_compact` | `compaction` (before) | |
| `compacted` | `session_compact` | `compaction` (after), with Pi's summary archived | the next `brief` returns the restored memory |
| `tree` | `session_tree` | a new engine branch: the session continues as `<session>~<leaf>`, forked from the branch it left, with Pi's branch summary archived | the next `brief` is for the new branch |
| `shutdown` | `session_shutdown` | `session_end` (quit, new, resume, fork or reload) | |

**Pi's session tree, mapped onto the core's own structure, with no core change:**
- **A forked or cloned session** (`/fork`, `/clone`, `--fork`) is a new Pi session whose header names its
  parent. Its `session_start` carries `forked_from`, so the core links it to the parent (`based_on`) and
  proposes it as a development path, as for any fork.
- **A branch inside one session** (`/tree`) keeps Pi's session file but changes the active line. The engine
  gives each line its own session, `<session>~<leaf>`, forked from the line it left. Records made on a branch
  stay on that branch.

**Compaction:** Pi has no hook that adds instructions to its summary. The memory section is part of the
system prompt, which Pi keeps across compaction (the compaction entry stores it), and it is refreshed with
the restored memory right after.
"""
from __future__ import annotations

import json
import re
import time

from agent_memory.adapters import idempotency
from agent_memory.adapters import claude_code as cc
from agent_memory.schema import EventInput

AGENT = "pi"
INJECT_CHARS = cc.INJECT_CHARS
EDIT_TOOLS = {"edit", "write"}
SHELL_TOOLS = {"bash"}
_SESSION_FILE = re.compile(r"_([^_/\\]+)\.jsonl$")


def session_id_of_file(path: str | None) -> str | None:
    """A Pi session file (`<timestamp>_<session-id>.jsonl`) to its session id."""
    m = _SESSION_FILE.search(path or "")
    return m.group(1) if m else None


class Hook(cc.Hook):
    agent = AGENT

    def __init__(self, store, project: str, event: str, payload: dict):
        # Pi names its session; the engine records on the session's current branch (see `tree`).
        pi_session = str(payload.get("session_id") or "unknown")
        self.pi_session = pi_session
        branch = cc._State(store, AGENT).get("pi", f"branch:{pi_session}")
        super().__init__(store, project, event, dict(payload, session_id=branch or pi_session))

    def output(self, text: str | None) -> str:
        return cc._fit(text, INJECT_CHARS) if text else ""


def _paths(h: Hook, args: dict) -> list[str]:
    rel = cc.relative(h.project, args.get("path") or args.get("file_path"))
    return [] if cc._outside(rel) else [rel]


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


# ------------------------------------------------------------ events
def _start(h: Hook, source: str, **extra) -> None:
    if h.state.get("session", f"started:{h.session}"):
        return
    if source in ("startup", "reload") and h.state.get("session", f"seen:{h.session}"):
        source = "resume"   # Pi says "startup" for `--session <file>`: the engine has seen this session before
    # Each start of a session is its own record (a resume can look exactly like the first start); a retried
    # delivery of the same start finds the session started and stops above.
    starts = h.state.get("session", f"starts:{h.session}", 0)
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
                               "environment": env, "agent_version": p.get("version"),
                               "pi_session": h.pi_session, "session_file": p.get("session_file"),
                               "capture": "extension: prompts, tools, assistant messages, compactions, branches",
                               **extra}, part=f"start:{h.session}:{starts}")
    h.state.set("session", f"starts:{h.session}", starts + 1)
    h.state.set("session", f"started:{h.session}", True)
    h.state.set("session", f"seen:{h.session}", True)
    h.mark_current()
    h.reconcile()


def session(h: Hook) -> str:
    reason = str(h.payload.get("reason") or "startup")
    extra = {}
    # A session whose header names a parent is a fork or clone. Pi reports `--fork` at process start as
    # "startup", so the header decides, not the reason.
    if h.payload.get("parent_session_file"):
        parent = session_id_of_file(h.payload.get("parent_session_file"))
        if parent:
            parent_branch = cc._State(h.store, AGENT).get("pi", f"branch:{parent}") or parent
            extra = {"forked_from": parent_branch, "fork_entry": h.payload.get("fork_entry")}
    _start(h, reason, **extra)
    h.mark_current()   # resuming or reloading makes this the current session again
    return ""


def brief(h: Hook) -> str:
    _start(h, "resume")   # an extension loaded mid-session saw no session_start
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
    _start(h, "resume")
    h.append("user_message", {"text": text[:500], "chars": len(text), "leaf": h.payload.get("leaf_id")},
             payload=text.encode())
    h.reconcile()
    if not text.strip():
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
    paths = _paths(h, args) if tool in EDIT_TOOLS else []
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
        h.append("tool_call", {"tool": tool, "command": command, "tool_use_id": call}, payload=command.encode())
        return ""
    h.append("tool_call", {"tool": tool, "tool_use_id": call, "parent_call": p.get("parent_call_id")},
             payload=json.dumps(args, ensure_ascii=False).encode())
    return ""


def tool_after(h: Hook) -> str:
    p = h.payload
    tool, args, call = str(p.get("tool") or "?"), p.get("args") or {}, p.get("call_id")
    structured = p.get("structured") if isinstance(p.get("structured"), dict) else {}
    body = _text(p.get("content"))
    failed = bool(p.get("is_error"))
    exit_code = structured.get("exit_code") if isinstance(structured.get("exit_code"), int) else None
    summary = {"tool": tool, "tool_use_id": call, "failed": failed or None, "duration_ms": p.get("duration_ms")}
    if failed:
        summary["error"] = body.splitlines()[0][:200] if body else ""
    paths = _paths(h, args) if tool in EDIT_TOOLS else []
    if paths:
        for rel in paths:
            after = cc._file_bytes(h.project, rel)
            h.append("tool_result", dict(summary, path=rel, before_object=h.state.get("tool", f"before:{call}:{rel}"),
                                         after_object=h.store.content_id(after, rel) if after is not None else None),
                     payload=body.encode(), part=rel)
        return ""
    if tool in SHELL_TOOLS:
        summary.update({"command": args.get("command"),
                        "exit_code": exit_code if exit_code is not None else (1 if failed else 0)})
    h.append("tool_result", summary, payload=body.encode())
    if tool in SHELL_TOOLS:
        h.reconcile()
        command = str(args.get("command") or "")
        if cc.TEST_COMMAND.search(command) and "software" in h.store.profiles:
            h.store.record_verification(h.session, h.writer, command, "failed" if failed else "passed",
                                        summary["exit_code"], output=body.encode(),
                                        environment=h.store.environment or {},
                                        idempotency_key=idempotency(AGENT, h.event, h.payload, "verification"))
    return ""


def text(h: Hook) -> str:
    body = str(h.payload.get("text") or "")
    if not body.strip():
        return ""
    stamp = h.payload.get("timestamp")
    h.append("assistant_message", {"text": body[:500], "chars": len(body), "model": h.payload.get("model"),
                                   "stop_reason": h.payload.get("stop_reason")},
             payload=body.encode(), key=f"{AGENT}:message:{h.pi_session}:{stamp}:{cc._digest(body)}")
    return ""


def idle(h: Hook) -> str:
    h.reconcile()
    return ""


def compacting(h: Hook) -> str:
    h.append("compaction", {"phase": "before", "trigger": h.payload.get("reason")})
    h.state.set("session", f"compacted:{h.session}", True)   # also if the process ends before session_compact
    return ""


def compacted(h: Hook) -> str:
    summary = h.payload.get("summary")
    h.append("compaction", {"phase": "after", "trigger": h.payload.get("reason"),
                            "summary_chars": len(summary) if summary else None},
             payload=str(summary).encode() if summary else None)
    h.state.set("session", f"compacted:{h.session}", True)
    return ""


def tree(h: Hook) -> str:
    """Pi moved to another line of its session tree: the engine continues on a new branch session."""
    new_leaf = h.payload.get("new_leaf")
    if not new_leaf:
        return ""
    left = h.session
    branch = f"{h.pi_session}~{new_leaf}"
    h.append("session_end", {"reason": "tree", "continues_as": branch})
    h.state.set("pi", f"branch:{h.pi_session}", branch)
    child = Hook(h.store, h.project, h.event, dict(h.payload, session_id=h.pi_session))
    summary = h.payload.get("summary")
    _start(child, "tree", forked_from=left, fork_entry=new_leaf, left_leaf=h.payload.get("old_leaf"))
    if summary:
        child.append("note", {"text": f"Pi's summary of the branch left behind ({left})", "source": "pi branch summary",
                              "chars": len(summary)}, payload=str(summary).encode(), part="branch-summary")
    return ""


def shutdown(h: Hook) -> str:
    h.store.defer_upkeep = True
    h.append("session_end", {"reason": h.payload.get("reason") or "quit"})
    h.state.set("session", f"started:{h.session}", False)   # if it comes back, that is a new start (a resume)
    return ""


HANDLERS = {"session": session, "brief": brief, "prompt": prompt, "tool_before": tool_before,
            "tool_after": tool_after, "text": text, "idle": idle, "compacting": compacting,
            "compacted": compacted, "tree": tree, "shutdown": shutdown}


# ------------------------------------------------------------ entry point
def handle(event: str, stdin: bytes, environ: dict, store=None) -> tuple[str, int]:
    """One extension event. Never raises: Pi is never blocked by memory."""
    from agent_memory.location import store_path
    started = time.perf_counter()
    try:
        payload = json.loads(stdin.decode("utf-8", errors="replace") or "{}")
        payload = payload if isinstance(payload, dict) else {}
    except ValueError:
        payload = {}
    project = cc.native(environ.get("AMEM_PROJECT") or payload.get("cwd") or ".")
    store_dir = store_path(project, environ.get("AMEM_HOME"))
    handler = HANDLERS.get(event)
    if handler is None:
        return "", 0
    try:
        store = store if store is not None else cc._open(store_dir, environ)
    except Exception as err:
        cc._spool(store_dir, event, payload, err, agent=AGENT)
        cc._log(store_dir, event, f"store unavailable: {type(err).__name__}: {err}")
        if event == "brief":
            return (f"agent-memory couldn't open this project's memory ({type(err).__name__}: {err}). "
                    "This session isn't being remembered; Pi works as usual.")[:INJECT_CHARS], 0
        return "", 0
    session_id = str(payload.get("session_id") or "unknown")
    try:
        out = handler(Hook(store, project, event, payload))
    except Exception as err:
        cc._log(store.path, event, f"{type(err).__name__}: {err}")
        store.safe_append(EventInput(kind="capture_gap", session_id=session_id, writer_id=f"{AGENT}:{session_id}",
                                     agent=AGENT, completeness="unavailable",
                                     summary_fields={"missed_kind": f"pi {event}",
                                                     "reason": f"{type(err).__name__}: {err}"[:300]}))
        out = ""
    if environ.get("AMEM_HOOK_TIMING"):
        cc._log(store.path, event, f"took {1000 * (time.perf_counter() - started):.1f} ms")
    return out or "", 0
