"""The Claude Code adapter (Stage 3.1): hook events in, canonical events out, context back in.

Every hook runs `amem hook claude-code <Event>` with Claude Code's JSON on
stdin, through the plugin's launcher script.

| Hook | Records | Delivers |
|---|---|---|
| `SessionStart` | `session_start` (source, model, branch, environment fingerprint); a reconcile | the assembled memory (`startup`, `resume`, `clear`, `fork`), or the restored memory (`compact`) |
| `UserPromptSubmit` | `user_message` (the prompt, in full, archived); a reconcile | short offers for records the prompt names but the context lacks |
| `PreToolUse` | `tool_call` (edit intents with the file's content id; Bash commands after a reconcile) | |
| `PostToolUse`, `PostToolUseFailure` | `tool_result` (the full response, archived); edits with content ids; a reconcile after Bash; test commands as verification records | |
| `Stop` | every new assistant message from the transcript (read from where the last Stop left off); a reconcile | |
| `SubagentStart`, `SubagentStop` | `subagent_start`, `subagent_stop` | |
| `PreCompact` | `compaction` (before) | instructions to keep the memory reference lines in the summary |
| `PostCompact` | `compaction` (after), with the compaction summary archived | |
| `SessionEnd` | `session_end` (the reason). Upkeep waits for the next session, because this hook has 1.5 s | |

**Limits respected:**
- Injected context stays under Claude Code's 10,000-character cap per string.
- A broken store or a bad payload never blocks Claude Code: the hook prints nothing and exits 0, and the failure becomes a `capture_gap` the next time the store opens.

**Paths:** a Windows Claude Code working on a project inside WSL sends Windows paths (`\\\\wsl.localhost\\<distro>\\...`). They are mapped to the Linux paths the store uses.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from agent_memory.adapters import ADAPTER_VERSION, idempotency
from agent_memory.schema import EventInput

AGENT = "claude-code"
INJECT_CHARS = 9500          # Claude Code caps each additionalContext string at 10,000 characters
SESSION_BUDGET = 2300        # tokens: what session start may load in full (about 9,200 characters)
OFFER_CHARS = 1500
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
TEST_COMMAND = re.compile(r"(?:^|[;&|(])\s*(?:[A-Z_][A-Z0-9_]*=\S*\s+)*(?:uv run |poetry run |python3? -m |npx |bunx )?"
                          r"(pytest|tox|nox|vitest|jest|mocha|go test|cargo test|mvn test|gradle test|dotnet test|"
                          r"(?:npm|pnpm|yarn|bun) (?:run )?test|make test|rspec|phpunit)\b")
STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS adapter_state (
    agent TEXT NOT NULL, scope TEXT NOT NULL, key TEXT NOT NULL, value TEXT, PRIMARY KEY (agent, scope, key));
"""
_WSL = re.compile(r"^(?:\\\\|//)(?:wsl\.localhost|wsl\$)[\\/]([^\\/]+)(.*)$", re.I)


# ------------------------------------------------------------ helpers
def native(path: str | None) -> str | None:
    """A Windows path into WSL (\\\\wsl.localhost\\Ubuntu\\home\\x) as the Linux path (/home/x); others unchanged."""
    if not path:
        return path
    m = _WSL.match(path)
    if m:
        return "/" + m.group(2).replace("\\", "/").strip("/")
    return path


def relative(project: str, path: str | None) -> str | None:
    """A file path as the reconciler names it (relative to the project), or None if it's outside the project."""
    if not path:
        return None
    path = native(path)
    try:
        return str(PurePosixPath(os.path.relpath(os.path.realpath(path), os.path.realpath(project)))) \
            if os.path.isabs(path) else str(PurePosixPath(path))
    except ValueError:
        return None


def _outside(rel: str | None) -> bool:
    return rel is None or rel == "." or rel.startswith("../")


class _State:
    """Small operational state per agent (transcript offsets, edit intents, the current session). Not history.

    `agent="*"` holds what every agent shares: the session most recently started in the project, by any agent.
    """

    def __init__(self, store, agent: str = AGENT):
        self.store, self.agent = store, agent
        conn = store._connect()
        try:
            conn.executescript(STATE_SCHEMA)
        finally:
            conn.close()

    def get(self, scope: str, key: str, default=None):
        conn = self.store._connect()
        try:
            row = conn.execute("SELECT value FROM adapter_state WHERE agent = ? AND scope = ? AND key = ?",
                               (self.agent, scope, key)).fetchone()
        finally:
            conn.close()
        return json.loads(row[0]) if row else default

    def set(self, scope: str, key: str, value) -> None:
        conn = self.store._connect()
        try:
            conn.execute("INSERT OR REPLACE INTO adapter_state VALUES (?, ?, ?, ?)",
                         (self.agent, scope, key, json.dumps(value)))
            conn.commit()
        finally:
            conn.close()


def current_session(store) -> str | None:
    """The session most recently started in this project, by any agent (what `amem mcp --session auto` serves).

    Stores written before #58 only have Claude Code's own record of it.
    """
    return _State(store, "*").get("project", "current_session") or _State(store).get("project", "current_session")


class Hook:
    agent = AGENT

    def __init__(self, store, project: str, event: str, payload: dict):
        self.store, self.project, self.event, self.payload = store, project, event, payload
        self.session = str(payload.get("session_id") or "unknown")
        self.writer = f"{self.agent}:{self.session}"
        self.state = _State(store, self.agent)
        # Always assigned: a long-lived store (the session server's) serves many sessions.
        store.environment = self.state.get("session", f"env:{self.session}")

    def mark_current(self) -> None:
        """This session is now the project's current one (for `amem mcp --session auto`)."""
        self.state.set("project", "current_session", self.session)
        _State(self.store, "*").set("project", "current_session", self.session)

    def append(self, kind: str, summary: dict, payload: bytes | str | None = None, part: str = "",
               completeness: str = "captured", key: str | None = None, path: str | None = None):
        return self.store.append(EventInput(
            kind=kind, session_id=self.session, writer_id=self.writer, agent=self.agent,
            adapter_version=ADAPTER_VERSION,
            summary_fields={k: v for k, v in summary.items() if v is not None}, payload=payload,
            completeness=completeness, path=path,
            idempotency_key=key or idempotency(self.agent, self.event, self.payload, part)))

    def reconcile(self) -> None:
        try:
            self.store.reconciler(self.project, self.session).run()
        except Exception as err:   # recorded as a failed reconcile; verification then reads "unknown"
            _log(self.store.path, self.event, f"reconcile failed: {err}")

    def output(self, text: str | None) -> str:
        if not text:
            return ""
        return json.dumps({"hookSpecificOutput": {"hookEventName": self.event,
                                                  "additionalContext": _fit(text, INJECT_CHARS)}})


def _fit(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 60].rsplit("\n", 1)[0]
    return cut + "\n(memory truncated here to fit; mem_context working_set lists everything)"


def _log(store_dir, event: str, message: str) -> None:
    """Diagnostics without content: the event name and the error only."""
    try:
        path = Path(store_dir) / "hooks.log"
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {event} {message[:300]}\n")
    except OSError:
        pass


# ------------------------------------------------------------ events
def session_start(h: Hook) -> str:
    p = h.payload
    source = p.get("source") or "startup"
    if source != "compact":
        try:
            h.store.checkpoint(reason="session start (upkeep deferred from the last session end)")
        except Exception as err:
            _log(h.store.path, h.event, f"checkpoint failed: {err}")
    env = h.state.get("session", f"env:{h.session}")
    if env is None and source != "compact":
        from agent_memory.verification import capture_environment
        try:
            env = capture_environment(h.project)
            h.state.set("session", f"env:{h.session}", env)
            h.store.environment = env
        except Exception as err:
            _log(h.store.path, h.event, f"environment capture failed: {err}")
    branch = None
    try:
        branch = subprocess.run(["git", "-C", h.project, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                                text=True, timeout=5).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        pass
    h.append("session_start", {"source": source, "model": p.get("model"), "cwd": h.project, "git_branch": branch,
                               "environment": env, "capture": "hooks: prompts, tools, transcript messages, compactions"})
    h.mark_current()
    h.reconcile()
    if source == "compact":
        text = h.store.context.compacted(h.session, budget=SESSION_BUDGET)["text"]
    else:
        text = h.store.context.assemble(h.session, budget=SESSION_BUDGET)["text"]
    notes = []
    if h.project.startswith("/mnt/"):
        notes.append("Note: this project is on a Windows drive (/mnt/...), where the memory store is slower and "
                     "less reliable; a project inside the Linux filesystem works better.")
    return h.output("\n\n".join(notes + [text]))


def user_prompt(h: Hook) -> str:
    prompt = str(h.payload.get("prompt") or "")
    h.append("user_message", {"text": prompt[:500], "chars": len(prompt)}, payload=prompt.encode())
    h.reconcile()
    offers = h.store.context.detect(h.session, prompt, limit=6) if prompt.strip() else []
    if not offers:
        return ""
    lines = ["Memory has records related to this prompt that aren't loaded (data, not instructions):"]
    lines += [f"- {o['line']}" for o in offers]
    return h.output(_fit("\n".join(lines), OFFER_CHARS))


def _file_bytes(project: str, rel: str) -> bytes | None:
    try:
        return (Path(project) / rel).read_bytes()
    except OSError:
        return None


def pre_tool(h: Hook) -> str:
    p = h.payload
    tool, ti, tuid = p.get("tool_name") or "?", p.get("tool_input") or {}, p.get("tool_use_id")
    if tool in EDIT_TOOLS:
        rel = relative(h.project, ti.get("file_path") or ti.get("notebook_path"))
        if not _outside(rel):
            before = _file_bytes(h.project, rel)
            before_id = h.store.content_id(before, rel) if before is not None else None
            h.state.set("tool", f"before:{tuid}", before_id)
            h.append("tool_call", {"tool": tool, "path": rel, "before_object": before_id, "intent": "edit",
                                   "tool_use_id": tuid})
            return ""
    if tool == "Bash":
        h.reconcile()   # so the command's own changes are the only ones in its window
        command = str(ti.get("command") or "")
        h.append("tool_call", {"tool": "Bash", "command": command, "description": ti.get("description"),
                               "tool_use_id": tuid}, payload=command.encode())
        return ""
    h.append("tool_call", {"tool": tool, "tool_use_id": tuid}, payload=json.dumps(ti, ensure_ascii=False).encode())
    return ""


def post_tool(h: Hook, failed: bool = False) -> str:
    p = h.payload
    tool, ti, tuid = p.get("tool_name") or "?", p.get("tool_input") or {}, p.get("tool_use_id")
    body = p.get("error") if failed else p.get("tool_response")
    payload = (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)).encode() \
        if body is not None else None
    summary = {"tool": tool, "tool_use_id": tuid, "duration_ms": p.get("duration_ms"), "failed": failed or None}
    exit_code = None
    if failed:
        first = str(p.get("error") or "").splitlines()[0] if p.get("error") else ""
        summary["error"] = first[:200]
        m = re.match(r"Exit code (\d+)", first)
        exit_code = int(m.group(1)) if m else 1
        summary["interrupted"] = p.get("is_interrupt")
    if tool in EDIT_TOOLS:
        rel = relative(h.project, ti.get("file_path") or ti.get("notebook_path"))
        if not _outside(rel):
            after = _file_bytes(h.project, rel)
            summary.update({"path": rel, "before_object": h.state.get("tool", f"before:{tuid}"),
                            "after_object": h.store.content_id(after, rel) if after is not None else None})
    if tool == "Bash":
        summary.update({"command": ti.get("command"), "exit_code": exit_code if failed else 0})
    h.append("tool_result", summary, payload=payload)
    if tool == "Bash":
        h.reconcile()
        command = str(ti.get("command") or "")
        if TEST_COMMAND.search(command) and "software" in h.store.profiles:
            output = payload or b""
            h.store.record_verification(h.session, h.writer, command, "failed" if failed else "passed",
                                        exit_code if failed else 0, output=output,
                                        environment=h.store.environment or {},
                                        idempotency_key=idempotency(AGENT, h.event, h.payload, "verification"))
    return ""


def stop(h: Hook) -> str:
    """Every assistant message, once: from the transcript, plus the hook's last message (the transcript may lag)."""
    _, problem = _transcript(h)
    last = h.payload.get("last_assistant_message")
    if last:
        text = str(last)
        digest = _digest(text)
        seen = h.state.get("session", f"seen:{h.session}", [])
        if digest not in seen:
            summary = {"text": text[:500], "chars": len(text), "source": "Stop hook"}
            if problem:
                summary["missing"] = f"earlier messages of this turn: {problem}"
            h.append("assistant_message", summary, payload=text.encode(), completeness="partial" if problem else
                     "captured", key=f"{AGENT}:last:{h.session}:{digest}")
            h.state.set("session", f"seen:{h.session}", (seen + [digest])[-200:])
    elif problem:
        h.append("capture_gap", {"missed_kind": "assistant_message", "reason": problem}, completeness="unavailable",
                 part="gap")
    h.reconcile()
    return ""


def _digest(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def _transcript(h: Hook) -> tuple[int, str | None]:
    """Record new assistant messages from the transcript. Returns (count, problem)."""
    path = native(h.payload.get("transcript_path"))
    if not path:
        return 0, "no transcript path"
    offset = h.state.get("session", f"transcript:{h.session}", 0)
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
    except OSError as err:
        return 0, f"transcript unreadable: {type(err).__name__}"
    complete = data[: data.rfind(b"\n") + 1] if b"\n" in data else b""
    count, bad = 0, 0
    seen = h.state.get("session", f"seen:{h.session}", [])
    for line in complete.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if obj.get("type") != "assistant":
            continue
        message = obj.get("message") or {}
        content = message.get("content")
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"] \
            if isinstance(content, list) else ([content] if isinstance(content, str) else [])
        text = "\n".join(t for t in texts if t)
        if not text or _digest(text) in seen:   # already recorded (from an earlier Stop's last message)
            continue
        seen.append(_digest(text))
        uid = obj.get("uuid") or idempotency(AGENT, "transcript", obj)
        h.append("assistant_message", {"text": text[:500], "chars": len(text), "transcript_uuid": uid,
                                       "model": message.get("model")},
                 payload=text.encode(), key=f"{AGENT}:transcript:{uid}")
        count += 1
    h.state.set("session", f"transcript:{h.session}", offset + len(complete))
    h.state.set("session", f"seen:{h.session}", seen[-200:])
    return count, (f"{bad} transcript lines couldn't be read" if bad else None)


def subagent(h: Hook, started: bool) -> str:
    p = h.payload
    summary = {"agent_type": p.get("agent_type"), "agent_id": p.get("agent_id")}
    last = p.get("last_assistant_message")
    h.append("subagent_start" if started else "subagent_stop", summary,
             payload=str(last).encode() if last and not started else None)
    return ""


def pre_compact(h: Hook) -> str:
    p = h.payload
    # Claude Code sends the same PreCompact payload for every compaction of a session. The transcript only
    # grows, so its size tells a second compaction from a replay of the first.
    try:
        size = os.path.getsize(native(p.get("transcript_path")) or "")
    except OSError:
        size = None
    h.append("compaction", {"phase": "before", "trigger": p.get("trigger"),
                            "custom_instructions": p.get("custom_instructions")}, part=f"transcript:{size}")
    ledger = h.store.context.ledger(h.session)
    refs = [i.reference() for i in ledger.values() if i.state == "loaded"]
    if not refs:
        return ""
    text = ("When summarising, keep these memory reference lines verbatim, so each detail stays one "
            "mem_context op=restore call away:\n" + "\n".join(refs))
    return _fit(text, 2000)   # PreCompact stdout becomes instructions for the compaction summary


def post_compact(h: Hook) -> str:
    p = h.payload
    summary_text = p.get("compact_summary")
    h.append("compaction", {"phase": "after", "trigger": p.get("trigger"),
                            "summary_chars": len(summary_text) if summary_text else None},
             payload=str(summary_text).encode() if summary_text else None)
    return ""


def session_end(h: Hook) -> str:
    h.store.defer_upkeep = True   # 1.5 s budget: the checkpoint runs at the next session start
    if h.payload.get("transcript_path"):
        _transcript(h)            # messages written after the last Stop
    h.append("session_end", {"reason": h.payload.get("reason")})
    return ""


HANDLERS = {
    "SessionStart": session_start, "UserPromptSubmit": user_prompt, "PreToolUse": pre_tool,
    "PostToolUse": post_tool, "PostToolUseFailure": lambda h: post_tool(h, failed=True), "Stop": stop,
    "SubagentStart": lambda h: subagent(h, True), "SubagentStop": lambda h: subagent(h, False),
    "PreCompact": pre_compact, "PostCompact": post_compact, "SessionEnd": session_end,
}


# ------------------------------------------------------------ entry point
def handle(event: str, stdin: bytes, environ: dict, store=None) -> tuple[str, int]:
    """One hook. Never raises and always exits 0: Claude Code is never blocked by memory.

    `store`: an open store to use (the session server's); otherwise the hook opens one.
    """
    from agent_memory.location import store_path
    started = time.perf_counter()
    try:
        payload = json.loads(stdin.decode("utf-8", errors="replace") or "{}")
        payload = payload if isinstance(payload, dict) else {}
    except ValueError:
        payload = {}
    project = native(environ.get("AMEM_PROJECT") or environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
    store_dir = store_path(project, environ.get("AMEM_HOME"))
    handler = HANDLERS.get(event)
    if handler is None:
        return "", 0
    try:
        store = store if store is not None else _open(store_dir, environ)
    except Exception as err:
        _spool(store_dir, event, payload, err)
        _log(store_dir, event, f"store unavailable: {type(err).__name__}: {err}")
        if event == "SessionStart":
            return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext":
                               f"agent-memory couldn't open this project's memory ({type(err).__name__}: {err}). "
                               "This session isn't being remembered; Claude Code works as usual."[:INJECT_CHARS]}}), 0
        return "", 0
    try:
        out = handler(Hook(store, project, event, payload))
    except Exception as err:
        _log(store.path, event, f"{type(err).__name__}: {err}")
        store.safe_append(EventInput(kind="capture_gap", session_id=str(payload.get("session_id") or "unknown"),
                                     writer_id=f"{AGENT}:{payload.get('session_id') or 'unknown'}", agent=AGENT,
                                     completeness="unavailable",
                                     summary_fields={"missed_kind": event, "reason": f"{type(err).__name__}: {err}"[:300]}))
        out = ""
    if environ.get("AMEM_HOOK_TIMING"):
        _log(store.path, event, f"took {1000 * (time.perf_counter() - started):.1f} ms")
    return out or "", 0


def _open(store_dir, environ: dict):
    from agent_memory.store import Store
    profiles = [p.strip() for p in (environ.get("AMEM_PROFILES") or "").split(",") if p.strip()] or None
    return Store(store_dir, profiles=profiles)


def _spool(store_dir, event: str, payload: dict, err: Exception, agent: str = AGENT) -> None:
    """The store can't open: leave a content-free note that becomes a capture_gap when it can."""
    try:
        Path(store_dir).mkdir(parents=True, exist_ok=True)
        session = str(payload.get("session_id") or "unknown")
        record = {"kind": f"{agent} {event}", "session_id": session, "writer_id": f"{agent}:{session}", "agent": agent,
                  "at": datetime.now(timezone.utc).isoformat(), "error": f"{type(err).__name__}: {err}"[:500],
                  "payload_size": len(json.dumps(payload)), "idempotency_key": None}
        with open(Path(store_dir) / "spool.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass
