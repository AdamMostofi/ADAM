"""Reconciliation: memory against the real files and git (design section 8.1, tested in the 2.1 spike).

`Reconciler.run()` finds every file that differs from the last version the
store recorded, works out how each change came about, and records it:

1. **Candidates.**
   - In a git repository: `git --no-optional-locks status` (so the project's
     `.git/index` is never written), plus files dirty at the last reconcile,
     plus files that differ between the old and new `HEAD`.
   - Elsewhere: every listed file, with a size and mtime fast path.
   - On a full run (`run(full=True)`): every listed file, all rehashed.
2. **Compare by content id.** The keyed hash of the redacted content, the
   same id the archive uses, so no plain hash of user content is stored.
3. **Attribute each change.** It never guesses:
   - `git_operation`: a working-tree git operation (from the reflog) changed
     it, and it now matches `HEAD`;
   - `agent_tool`: an agent tool edit reported exactly this content;
   - `agent_bash`: a Bash command since the last reconcile names the path;
   - `external`: no agent activity, and the previous session ended cleanly;
   - `unattributed`: anything else.
4. **Group large git operations.** More than 100 files go into one
   `change_group` record, with every file still listed.
5. **Record conflicts.** A tool edit whose before-content doesn't match the
   last known content gives a `conflict` record, not an overwrite.
6. **Resolve open intents.** A tool call that announced an edit but never
   reported back (the agent crashed) is settled by the file's content.

If anything fails, the reconcile state is marked failed, and verification
status reads `unknown` until a reconcile succeeds.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

WORKTREE_GIT = re.compile(r"^(checkout|pull|reset|merge|rebase|cherry-pick|revert|switch|am|stash)\b")
GROUP_THRESHOLD = 100
LARGE_RECONCILE = 500
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "edit", "write", "apply_patch", "str_replace_editor"}
SHELL_TOOLS = {"Bash", "bash", "shell", "run_shell_command", "terminal"}
WALK_SKIP = {".git", ".agent-memory", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS reconcile_files (path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER, content_id TEXT);
CREATE TABLE IF NOT EXISTS reconcile_meta (key TEXT PRIMARY KEY, value TEXT);
"""


class ReconcileError(RuntimeError):
    pass


@dataclass
class Change:
    path: str
    kind: str                 # added | modified | deleted | renamed
    attribution: str
    content: bytes | None = None
    old_path: str | None = None
    resolves_intent: str | None = None


@dataclass
class Result:
    changes: list[Change] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    group_event: str | None = None
    events: list[str] = field(default_factory=list)
    hashed: int = 0
    full: bool = False


class Reconciler:
    def __init__(self, store, root: str | os.PathLike, session_id: str, writer_id: str = "reconciler"):
        self.store = store
        self.root = Path(root).resolve()
        self.session_id = session_id
        self.writer_id = writer_id
        conn = store._connect()
        try:
            conn.executescript(SCHEMA)
        finally:
            conn.close()
        self.is_git = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--git-dir"],
                                     capture_output=True).returncode == 0

    # ------------------------------------------------------------ git and files
    def _git(self, *args: str, check: bool = True) -> str:
        out = subprocess.run(["git", "--no-optional-locks", "-C", str(self.root), *args],
                             capture_output=True, text=True)
        if check and out.returncode != 0:
            raise ReconcileError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
        return out.stdout

    def _head(self) -> str | None:
        out = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], capture_output=True, text=True)
        return out.stdout.strip() or None

    def _reflog(self) -> list[str]:
        return self._git("reflog", "--format=%gs", check=False).splitlines()

    def _listed(self) -> list[str]:
        if self.is_git:
            out = self._git("ls-files", "-co", "--exclude-standard", "-z")
            return sorted({p for p in out.split("\0") if p and (self.root / p).is_file()})
        files = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if d not in WALK_SKIP)
            for name in filenames:
                files.append(str((Path(dirpath) / name).relative_to(self.root)).replace(os.sep, "/"))
        return sorted(files)

    def _dirty(self) -> set[str]:
        out = self._git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
        return {entry[3:] for entry in out.split("\0") if len(entry) > 3}

    # ------------------------------------------------------------ state
    def _meta(self, conn, key, default=None):
        row = conn.execute("SELECT value FROM reconcile_meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def _set_meta(self, conn, key, value) -> None:
        conn.execute("INSERT OR REPLACE INTO reconcile_meta VALUES (?, ?)", (key, json.dumps(value)))

    def content_id(self, data: bytes, path: str) -> str:
        """The archive id of what the store would keep for this file (excluded files: a keyed fingerprint)."""
        if self.store._excluded(path):
            return "excluded:" + self.store.scanner.fingerprint(data)
        clean, _ = self.store.scanner.redact(data, "payload")
        return self.store.archive.object_id(clean)

    # ------------------------------------------------------------ observations from the log
    def _observations(self, since: int) -> dict:
        tool_after: dict[str, str] = {}
        intents: dict[str, dict] = {}
        conflicts: list[dict] = []
        commands: list[str] = []
        agent_active = False
        last_after: dict[str, str] = {}
        for ev in self.store.events():
            if ev.log_position <= since:
                continue
            s = ev.summary_fields
            if ev.kind in ("tool_call", "tool_result"):
                agent_active = True
                tool = s.get("tool")
                if tool in SHELL_TOOLS and s.get("command"):
                    commands.append(s["command"])
                if tool in EDIT_TOOLS and s.get("path"):
                    path = s["path"]
                    if s.get("after_object"):
                        known = last_after.get(path, self._baseline_id(path))
                        if s.get("before_object") and known is not None and s["before_object"] != known:
                            conflicts.append({"path": path, "writer": ev.writer_id, "event": ev.event_id,
                                              "expected_before": known, "reported_before": s["before_object"]})
                        last_after[path] = s["after_object"]
                        tool_after[path] = s["after_object"]
                    if s.get("intent") and ev.kind == "tool_call":
                        intents[path] = {"event": ev.event_id, "after_object": s.get("after_object")}
                    elif ev.kind == "tool_result":
                        intents.pop(path, None)
        return {"tool_after": tool_after, "intents": intents, "conflicts": conflicts, "commands": commands,
                "agent_active": agent_active}

    def _baseline_id(self, path: str) -> str | None:
        current = self._current.get(path)
        return current[0] if current else None

    def _previous_session_unclean(self) -> bool:
        """True if some other session started and never ended: its changes can't be called external."""
        started, ended = set(), set()
        for ev in self.store.events():
            if ev.session_id == self.session_id:
                continue
            if ev.kind == "session_start":
                started.add(ev.session_id)
            elif ev.kind == "session_end":
                ended.add(ev.session_id)
        return bool(started - ended)

    # ------------------------------------------------------------ run
    def run(self, full: bool = False) -> Result:
        conn = self.store._connect()
        try:
            return self._run(conn, full)
        except Exception as err:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            self._set_meta(conn, "ok", False)
            self._set_meta(conn, "error", str(err))
            conn.commit()
            raise
        finally:
            conn.close()

    def _run(self, conn, full: bool) -> Result:
        from agent_memory.schema import EventInput

        self._current = self.store.current_files()
        baseline = {p: oid for p, (oid, _) in self._current.items()}
        cache = {p: (s, m, c) for p, s, m, c in conn.execute("SELECT * FROM reconcile_files")}
        # Excluded files have no versions; their fingerprints live in the reconcile cache.
        for path, (_s, _m, cid) in cache.items():
            if cid and cid.startswith("excluded:"):
                baseline[path] = cid
        first_run = self._meta(conn, "head", "never") == "never"
        old_head = self._meta(conn, "head") if not first_run else None
        old_reflog = self._meta(conn, "reflog_len", 0)
        since = self._meta(conn, "log_position", 0)
        head = self._head() if self.is_git else None
        reflog = self._reflog() if self.is_git else []

        rehash = full   # an explicit full run hashes every file: the periodic full hash of 8.1
        full = full or first_run or not self.is_git
        if full:
            candidates = set(self._listed()) | set(baseline)
        else:
            candidates = self._dirty() | set(self._meta(conn, "dirty", []))
            if head != old_head and old_head and head:
                candidates |= set(self._git("diff", "--name-only", "--no-renames", old_head, head).splitlines())
            candidates |= {p for p in baseline if not (self.root / p).is_file()}
        if len(candidates) > LARGE_RECONCILE and not first_run:
            self.store.checkpoint(reason="before a large reconciliation")

        result = Result(full=full)
        now: dict[str, tuple[str, bytes]] = {}
        stat_cache: dict[str, tuple[int, int, str]] = {}
        for rel in sorted(candidates):
            path = self.root / rel
            if not path.is_file():
                continue
            st = path.stat()
            cached = cache.get(rel)
            # git already compared these candidates (including ctime and inode), so hash them all;
            # a plain walk may skip a file whose size and mtime are unchanged, unless this is a full rehash.
            if rehash or not full or cached is None or cached[0] != st.st_size or cached[1] != st.st_mtime_ns or \
                    baseline.get(rel) != cached[2]:
                data = path.read_bytes()
                cid = self.content_id(data, rel)
                result.hashed += 1
            else:
                data, cid = None, cached[2]
            now[rel] = (cid, data)
            stat_cache[rel] = (st.st_size, st.st_mtime_ns, cid)

        added = {p for p in now if p not in baseline}
        deleted = {p for p in candidates if p in baseline and p not in now}
        modified = {p for p in now if p in baseline and now[p][0] != baseline[p]}
        renames = {}
        by_id: dict[str, list[str]] = {}
        for p in sorted(deleted):
            by_id.setdefault(baseline[p], []).append(p)
        for p in sorted(added):
            olds = by_id.get(now[p][0])
            if olds:
                renames[p] = olds.pop(0)
        added -= set(renames)
        deleted -= set(renames.values())

        fresh = reflog[: max(0, len(reflog) - old_reflog)]
        git_files: set[str] = set()
        if self.is_git and head != old_head and old_head and any(WORKTREE_GIT.match(e) for e in fresh):
            git_files = set(self._git("diff", "--name-only", "--no-renames", old_head, head).splitlines())
            git_files -= self._dirty()
        obs = self._observations(since)
        unclean = self._previous_session_unclean()
        mentioned = set()
        for command in obs["commands"]:
            try:
                tokens = shlex.split(command)
            except ValueError:
                tokens = command.split()
            mentioned.update(t.lstrip("./") for t in tokens)

        def attribute(path: str, cid: str | None, old_path: str | None = None) -> str:
            if path in git_files or (old_path and old_path in git_files):
                return "git_operation"
            if cid is not None and obs["tool_after"].get(path) == cid:
                return "agent_tool"
            if obs["commands"] and (path in mentioned or (old_path and old_path in mentioned)):
                return "agent_bash"
            if not obs["agent_active"] and not unclean:
                return "external"
            return "unattributed"

        def content(p: str) -> bytes:
            return now[p][1] if now[p][1] is not None else (self.root / p).read_bytes()

        for p in sorted(added):
            result.changes.append(Change(p, "added", attribute(p, now[p][0]), content(p)))
        for p in sorted(modified):
            result.changes.append(Change(p, "modified", attribute(p, now[p][0]), content(p)))
        for p in sorted(deleted):
            result.changes.append(Change(p, "deleted", attribute(p, None)))
        for p, was in sorted(renames.items()):
            result.changes.append(Change(p, "renamed", attribute(p, now[p][0], was), content(p), old_path=was))
        for c in result.changes:
            intent = obs["intents"].get(c.path)
            if intent and intent.get("after_object") == (now.get(c.path) or (None,))[0]:
                c.resolves_intent = intent["event"]
                c.attribution = "agent_tool"
        if first_run:
            for c in result.changes:
                c.attribution = "baseline"   # the first look at the project: its existing files

        # Record: the group first, then every change, then conflicts.
        git_changes = [c for c in result.changes if c.attribution == "git_operation"]
        if len(git_changes) > GROUP_THRESHOLD:
            group = self.store.append(EventInput(
                kind="change_group", session_id=self.session_id, writer_id=self.writer_id,
                summary_fields={"reflog": fresh, "head": head, "count": len(git_changes),
                                "files": [[c.path, c.kind] for c in git_changes]}))
            result.group_event = group.event_id
        for c in result.changes:
            summary = {"path": c.path, "change": c.kind, "attribution": c.attribution, "git_commit": head,
                       "old_path": c.old_path, "size": len(c.content) if c.content is not None else None}
            if c.attribution == "git_operation" and result.group_event:
                summary["group"] = result.group_event
            if c.resolves_intent:
                summary["resolves_intent"] = c.resolves_intent
            ev = self.store.append(EventInput(kind="file_change", session_id=self.session_id,
                                              writer_id=self.writer_id, payload=c.content,
                                              summary_fields=summary, path=c.path,
                                              completeness="captured"))
            result.events.append(ev.event_id)
        for conflict in obs["conflicts"]:
            result.conflicts.append(conflict)
            self.store.append(EventInput(kind="conflict", session_id=self.session_id, writer_id=self.writer_id,
                                         summary_fields={"op": "create", "title": f"conflicting edits to {conflict['path']}",
                                                         **conflict}))

        # Remember what was seen.
        conn.execute("BEGIN IMMEDIATE")
        for p in deleted | set(renames.values()):
            conn.execute("INSERT OR REPLACE INTO reconcile_files VALUES (?, NULL, NULL, NULL)", (p,))
        for p, (size, mtime, cid) in stat_cache.items():
            conn.execute("INSERT OR REPLACE INTO reconcile_files VALUES (?, ?, ?, ?)", (p, size, mtime, cid))
        self._set_meta(conn, "head", head)
        self._set_meta(conn, "reflog_len", len(reflog))
        self._set_meta(conn, "dirty", sorted(self._dirty()) if self.is_git else [])
        last = conn.execute("SELECT COALESCE(MAX(log_position), 0) FROM events").fetchone()[0]
        self._set_meta(conn, "log_position", last)
        self._set_meta(conn, "ok", True)
        self._set_meta(conn, "error", None)
        conn.execute("COMMIT")
        return result


def reconcile_ok(store) -> bool:
    """False if the most recent reconciliation failed (verification status is then unknown)."""
    conn = store._connect()
    try:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'reconcile_meta'").fetchone()
        if not exists:
            return True
        row = conn.execute("SELECT value FROM reconcile_meta WHERE key = 'ok'").fetchone()
        return True if row is None else json.loads(row[0])
    finally:
        conn.close()
