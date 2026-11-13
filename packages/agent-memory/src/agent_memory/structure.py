"""The permanent core's structure: historical tree, relationships, paths, planning (design section 6).

Every structural fact comes from an event. `apply(conn, event)` is the only
writer of the structure tables. It runs in the same transaction as the event
insert, and it is a deterministic function of the event and the structure
already there:

* **Recorded** structure comes from ordinary events:
  - the project, session, turn and event nodes, joined by ordered
    `contains` edges;
  - `triggered_by` edges from an event's `parent_id`;
  - `modifies` edges from file changes;
  - session resume, fork and continuation links;
  - path proposals from structural signals: a session fork, a new git
    branch, or a reported revert.
* **Declared** structure comes from planning events: `path`, `goal`, `task`,
  `blocker`, `decision`, `note`, `relation` and `retraction`, each carrying
  its operation in `summary_fields`.

The tables are append-only, like the log:
- a status change is a new row in `statuses`;
- a withdrawn edge gets a row in `retractions`;
- nothing is updated or deleted.

Because structure is a pure function of the log, `rebuild()` can recompute
it from scratch. `Store.verify()` uses that to detect tampering with these
tables, and Stage 2.5's replay uses it for recovery.

The boundary rule (design 1): the engine records time order and observed
links. It never claims one event caused another unless an event declares it,
and every edge says how it is known (`basis`).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from agent_memory.schema import Event, SchemaError, canonical_json

EDGE_TYPES = frozenset({
    "contains", "follows", "part_of", "references",                                  # structure
    "triggered_by", "caused_by", "based_on", "in_response_to",                       # causality
    "modifies", "modified_by", "reverts", "reverted_by",                             # change
    "verifies", "verified_by", "supports", "contradicts",                            # evidence
    "supersedes", "superseded_by", "alternative_to", "selected_over", "abandoned_because",  # history
    "imports", "depends_on", "tests",                                                # code
    "blocks", "blocked_by", "advances",                                              # planning
    "related_to",                                                                    # general
})
BASES = ("recorded", "declared", "inferred")

STATUSES = {
    "path": ("proposed", "exploring", "selected", "abandoned", "superseded", "reconsidered"),
    "goal": ("active", "achieved", "dropped"),
    "task": ("open", "in_progress", "done", "blocked", "cancelled"),
    "decision": ("proposed", "active", "superseded"),
    "blocker": ("open", "resolved"),
}
INITIAL = {"path": "proposed", "goal": "active", "task": "open", "decision": "proposed", "blocker": "open"}
PLANNING_KINDS = {"path", "goal", "task", "blocker", "decision"}
PATH_ROLES = ("experiment", "accepted", "reverted")

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY, node_type TEXT NOT NULL, label TEXT, attrs TEXT NOT NULL,
    source_event TEXT NOT NULL, log_position INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS edges (
    edge_id INTEGER PRIMARY KEY AUTOINCREMENT, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
    type TEXT NOT NULL, basis TEXT NOT NULL, ord INTEGER, attrs TEXT NOT NULL,
    source_event TEXT NOT NULL, log_position INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS retractions (
    edge_id INTEGER NOT NULL, retracted_by TEXT NOT NULL, reason TEXT, log_position INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS statuses (
    node_id TEXT NOT NULL, status TEXT NOT NULL, reason TEXT, basis TEXT NOT NULL,
    source_event TEXT NOT NULL, log_position INTEGER NOT NULL, at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_id, type);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_id, type);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_statuses_node ON statuses(node_id);
"""
TABLES = ("nodes", "edges", "retractions", "statuses")


def create(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table in TABLES:
        for action in ("UPDATE", "DELETE"):
            conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_append_only_{action.lower()} BEFORE {action} "
                         f"ON {table} BEGIN SELECT RAISE(ABORT, 'the {table} table is append-only'); END")


# ------------------------------------------------------------ helpers
def session_node(session_id: str) -> str:
    return f"session:{session_id}"


def file_node(path: str) -> str:
    return f"file:{path}"


def _node_exists(conn, node_id: str) -> bool:
    return conn.execute("SELECT 1 FROM nodes WHERE node_id = ?", (node_id,)).fetchone() is not None


def _node_type(conn, node_id: str) -> str | None:
    row = conn.execute("SELECT node_type FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
    return row[0] if row else None


def _add_node(conn, node_id: str, node_type: str, ev: Event, label: str | None = None, **attrs) -> None:
    if not _node_exists(conn, node_id):
        conn.execute("INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?)",
                     (node_id, node_type, label, canonical_json(attrs), ev.event_id, ev.log_position))


def _add_edge(conn, src: str, dst: str, etype: str, basis: str, ev: Event, ord_: int | None = None, **attrs) -> None:
    conn.execute("INSERT INTO edges (from_id, to_id, type, basis, ord, attrs, source_event, log_position) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (src, dst, etype, basis, ord_, canonical_json(attrs), ev.event_id, ev.log_position))


def _add_status(conn, node_id: str, status: str, reason: str | None, basis: str, ev: Event) -> None:
    conn.execute("INSERT INTO statuses VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (node_id, status, reason, basis, ev.event_id, ev.log_position, ev.occurred_at))


def _next_ord(conn, parent: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(ord), 0) FROM edges WHERE from_id = ? AND type = 'contains'",
                       (parent,)).fetchone()
    return row[0] + 1


def _current_turn(conn, session: str) -> str | None:
    row = conn.execute("SELECT to_id FROM edges WHERE from_id = ? AND type = 'contains' AND to_id LIKE 'turn:%' "
                       "ORDER BY ord DESC LIMIT 1", (session,)).fetchone()
    return row[0] if row else None


def _ids(value: Any) -> list[str]:
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def current_status(conn, node_id: str) -> str | None:
    row = conn.execute("SELECT status FROM statuses WHERE node_id = ? ORDER BY log_position DESC, rowid DESC LIMIT 1",
                       (node_id,)).fetchone()
    return row[0] if row else None


# ------------------------------------------------------------ validation (before the event is stored)
def validate(conn, kind: str, summary: dict) -> None:
    """Reject a declared operation that can't be applied, so no event is stored for it."""
    op = summary.get("op")
    if kind in PLANNING_KINDS:
        if op not in ("create", "status"):
            raise SchemaError(f"a {kind} event needs op 'create' or 'status'")
        status = summary.get("status")
        if status is not None and status not in STATUSES[kind]:
            raise SchemaError(f"{kind} status {status!r} must be one of {STATUSES[kind]}")
        if op == "create" and not (summary.get("title") or summary.get("topic")):
            raise SchemaError(f"creating a {kind} needs a title (or, for a path, a topic)")
        if op == "status":
            target = summary.get("id")
            if not target or _node_type(conn, target) != kind:
                raise SchemaError(f"no {kind} with id {target!r}")
            if status is None:
                raise SchemaError("a status change needs a status")
        for ref in ("alternative_to", "supersedes"):
            for target in _ids(summary.get(ref)):
                if _node_type(conn, target) != kind:
                    raise SchemaError(f"{ref} must name existing {kind} records; {target!r} isn't one")
    elif kind == "relation":
        if summary.get("type") not in EDGE_TYPES:
            raise SchemaError(f"relation type must be one of {sorted(EDGE_TYPES)}")
        if summary.get("basis", "declared") not in ("declared", "inferred"):
            raise SchemaError("a relation event's basis is 'declared' or 'inferred'; 'recorded' is the engine's")
        for end in ("from", "to"):
            if not summary.get(end) or not _node_exists(conn, summary[end]):
                raise SchemaError(f"relation '{end}' must name an existing record")
    elif kind == "retraction":
        edge = summary.get("edge_id")
        if not isinstance(edge, int) or not conn.execute("SELECT 1 FROM edges WHERE edge_id = ?", (edge,)).fetchone():
            raise SchemaError("a retraction names an existing edge_id")
    path = summary.get("path_id")
    if path is not None and _node_type(conn, path) != "path":
        raise SchemaError(f"path_id {path!r} is not a development path")
    role = summary.get("path_role")
    if role is not None and role not in PATH_ROLES:
        raise SchemaError(f"path_role must be one of {PATH_ROLES}")


# ------------------------------------------------------------ apply
def apply(conn, ev: Event) -> None:
    s = ev.summary_fields
    _add_node(conn, "project", "project", ev, label="project")
    session = session_node(ev.session_id)
    if not _node_exists(conn, session):
        _add_node(conn, session, "session", ev, label=ev.session_id, agent=ev.agent)
        _add_edge(conn, "project", session, "contains", "recorded", ev, _next_ord(conn, "project"))

    # The event's place in the tree: a user message opens a turn; other events join the current turn.
    parent = session
    if ev.kind == "user_message":
        n = _next_ord(conn, session)
        turn = f"turn:{ev.session_id}:{n}"
        _add_node(conn, turn, "turn", ev, label=f"turn {n}")
        _add_edge(conn, session, turn, "contains", "recorded", ev, n)
        parent = turn
    else:
        parent = _current_turn(conn, session) or session
    _add_node(conn, ev.event_id, "event", ev, label=ev.kind, kind=ev.kind)
    _add_edge(conn, parent, ev.event_id, "contains", "recorded", ev, _next_ord(conn, parent))
    if ev.parent_id and _node_exists(conn, ev.parent_id):
        _add_edge(conn, ev.event_id, ev.parent_id, "triggered_by", "recorded", ev)

    if ev.kind == "session_start":
        _session_links(conn, ev, session, s)
    if ev.kind in ("file_change", "exclusion") and s.get("path"):
        f = file_node(s["path"])
        _add_node(conn, f, "file", ev, label=s["path"])
        _add_edge(conn, ev.event_id, f, "modifies", "recorded", ev)
        if s.get("restores_version"):
            _propose_path(conn, ev, f"revert of {s['path']} to an earlier version", "revert", [ev.event_id])
    if ev.kind == "verification":
        for target in _ids(s.get("verifies")):
            if _node_exists(conn, target):
                _add_edge(conn, ev.event_id, target, "verifies", "recorded", ev)
    if s.get("path_id"):
        _add_edge(conn, ev.event_id, s["path_id"], "part_of", "recorded", ev, role=s.get("path_role"))

    if ev.kind in PLANNING_KINDS:
        _planning(conn, ev, s)
    elif ev.kind == "note":
        _add_node(conn, f"note:{ev.event_id}", "note", ev, label=s.get("title") or s.get("text", "")[:80],
                  note_type=s.get("note_type", "note"))
        _add_edge(conn, f"note:{ev.event_id}", ev.event_id, "references", "recorded", ev)
        _declared_links(conn, ev, f"note:{ev.event_id}", s)
    elif ev.kind == "relation":
        _add_edge(conn, s["from"], s["to"], s["type"], s.get("basis", "declared"), ev, reason=s.get("reason"))
    elif ev.kind == "retraction":
        conn.execute("INSERT INTO retractions VALUES (?, ?, ?, ?)",
                     (s["edge_id"], ev.event_id, s.get("reason"), ev.log_position))


def _session_links(conn, ev: Event, session: str, s: dict) -> None:
    for key, etype, link in (("resumed_from", "follows", "resume"), ("forked_from", "based_on", "fork")):
        other = s.get(key)
        if other:
            _add_node(conn, session_node(other), "session", ev, label=other)
            _add_edge(conn, session, session_node(other), etype, "recorded", ev, link=link)
            if link == "fork":
                _propose_path(conn, ev, f"fork of session {other}", "session_fork", [ev.event_id], session=session)
    for other in _ids(s.get("continues")):
        _add_node(conn, session_node(other), "session", ev, label=other)
        _add_edge(conn, session, session_node(other), "based_on", "recorded", ev, link="continues")
    branch = s.get("git_branch")
    if branch:
        seen = conn.execute("SELECT 1 FROM nodes WHERE node_type = 'path' AND json_extract(attrs, '$.git_branch') = ?",
                            (branch,)).fetchone()
        if not seen and branch not in ("main", "master"):
            _propose_path(conn, ev, f"git branch {branch}", "git_branch", [ev.event_id], session=session,
                          git_branch=branch)


def _propose_path(conn, ev: Event, description: str, signal: str, evidence: list[str],
                  session: str | None = None, **attrs) -> None:
    """A structural signal proposes a path but doesn't name its topic (design 6.2)."""
    node = f"path:{ev.event_id}:{signal}"
    _add_node(conn, node, "path", ev, label=description, topic=None, description=description, signal=signal,
              source="recorded", **attrs)
    _add_status(conn, node, "proposed", f"structural signal: {signal}", "recorded", ev)
    for e in evidence:
        _add_edge(conn, e, node, "supports", "recorded", ev)
    if session:
        _add_edge(conn, session, node, "part_of", "recorded", ev, role="experiment")


def _planning(conn, ev: Event, s: dict) -> None:
    kind = ev.kind
    if s["op"] == "create":
        node = f"{kind}:{ev.event_id}"
        title = s.get("title") or s.get("topic")
        _add_node(conn, node, kind, ev, label=title, title=title, topic=s.get("topic"),
                  description=s.get("description"), source="declared")
        status = s.get("status") or INITIAL[kind]
        if kind == "decision" and s.get("status") is None and s.get("from_user_message"):
            status = "active"   # agent-declared decisions start as proposed; a user's are active
        _add_status(conn, node, status, s.get("reason"), "declared", ev)
        _add_edge(conn, node, ev.event_id, "references", "recorded", ev)
        _declared_links(conn, ev, node, s)
    else:
        node = s["id"]
        _add_status(conn, node, s["status"], s.get("reason"), "declared", ev)
        _add_edge(conn, node, ev.event_id, "references", "recorded", ev)
        if kind == "path":
            if s["status"] == "abandoned":
                for e in _ids(s.get("evidence")):
                    _add_edge(conn, node, e, "abandoned_because", "declared", ev)
            if s["status"] == "selected":
                for alt in _alternatives(conn, node):
                    _add_edge(conn, node, alt, "selected_over", "declared", ev)
        _declared_links(conn, ev, node, s, statuses_only=True)


def _declared_links(conn, ev: Event, node: str, s: dict, statuses_only: bool = False) -> None:
    for e in _ids(s.get("evidence")):
        if _node_exists(conn, e):
            _add_edge(conn, e, node, "supports", "declared", ev)
    if statuses_only:
        return
    for alt in _ids(s.get("alternative_to")):
        _add_edge(conn, node, alt, "alternative_to", "declared", ev)
    for target in _ids(s.get("based_on")):
        if _node_exists(conn, target):
            _add_edge(conn, node, target, "based_on", "declared", ev)
    for old in _ids(s.get("supersedes")):
        _add_edge(conn, node, old, "supersedes", "declared", ev)
        _add_status(conn, old, "superseded", f"superseded by {node}", "declared", ev)
    for goal in _ids(s.get("advances")):
        if _node_exists(conn, goal):
            _add_edge(conn, node, goal, "advances", "declared", ev)
    for other in _ids(s.get("blocks")):
        if _node_exists(conn, other):
            _add_edge(conn, node, other, "blocks", "declared", ev)
    for other in _ids(s.get("blocked_by")):
        if _node_exists(conn, other):
            _add_edge(conn, node, other, "blocked_by", "declared", ev)
    for cause in _ids(s.get("caused_by")):
        if _node_exists(conn, cause):
            _add_edge(conn, node, cause, "caused_by", "declared", ev)


def _alternatives(conn, node: str) -> list[str]:
    rows = conn.execute("SELECT to_id FROM edges WHERE from_id = ? AND type = 'alternative_to' "
                        "UNION SELECT from_id FROM edges WHERE to_id = ? AND type = 'alternative_to'",
                        (node, node)).fetchall()
    return sorted(r[0] for r in rows)


# ------------------------------------------------------------ rebuild (integrity and recovery)
def snapshot(conn) -> dict[str, list]:
    return {t: conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in TABLES}


def rebuild(events) -> dict[str, list]:
    """Structure recomputed from scratch by applying every event in log order."""
    mem = sqlite3.connect(":memory:")
    create(mem)
    for ev in events:
        apply(mem, ev)
    return snapshot(mem)
