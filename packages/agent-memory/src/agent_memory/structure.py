"""The permanent core's structure: four trees and the links between them (architecture revision 3, section 4).

Every structural fact comes from an event. `apply(conn, event)` is the only
writer of the structure tables. It runs in the same transaction as the event
insert, and it is a deterministic function of the event and the structure
already there. `rebuild()` recomputes everything from the log, which `verify`
and recovery use.

**Four trees, one store.** Every node belongs to exactly one tree:

| Tree | Root | Holds |
|---|---|---|
| history | `history:` | sessions, turns, events: what happened |
| artifacts | `artifacts:` | collections (folders) and artifacts (any file or resource), with versions: what exists |
| knowledge | `knowledge:` | a topic hierarchy holding entries (decisions, approaches, requirements, bugs, solutions ...): what is known |
| state | `state:` | sections of items: objectives, tasks, blockers, open conflicts: what matters now |

* **Tree structure:** each tree's shape is made by `contains` edges inside
  it, and checked against that tree's schema (`SCHEMAS`) on every write.
* **Cross-tree links:** edges whose ends are in different trees are marked
  `cross`, and they form the cross-tree relationship layer.

**Basis, on every node, status and edge:**
- `observed`: the engine saw it through an instrumented operation;
- `declared`: an agent or the user stated it;
- `inferred`: the engine derived it from evidence, and the rule is named in the record.

**Stable ids:** record ids that appear in the log never change.
- Planning records keep `<kind>:<event id>`. A development path is a knowledge
  `approach` whose id is still `path:...`.
- Artifacts are `artifact:<path>`. A legacy `file:<path>` reference, from a
  store written before format 2, resolves to the same node.

The tables are append-only, like the log:
- a status change is a new row in `statuses`;
- a withdrawn edge gets a row in `retractions`;
- nothing is updated or deleted.

The boundary rule: the engine records time order and observed links. It
never claims one event caused another unless an event declares it.
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
    "fixes", "fixed_by", "filed_under", "concerns", "discussed_in", "evidence_for",  # knowledge (Stage 2.8)
})
BASES = ("observed", "declared", "inferred")

TREES = ("history", "artifacts", "knowledge", "state")
# Per-tree schema: node type -> the node types it may contain.
SCHEMAS = {
    "history": {"root": ("session",), "session": ("turn", "event"), "turn": ("event",), "event": ()},
    "artifacts": {"root": ("collection", "artifact"), "collection": ("collection", "artifact"), "artifact": ()},
    # Stage 2.8: topics nest, and every entry has one home topic ("unfiled" when none was given).
    "knowledge": {"root": ("topic",),
                  "topic": ("topic", "decision", "approach", "note", "requirement", "constraint", "concept",
                            "explanation", "discovery", "bug", "solution", "question", "reference"),
                  **{k: () for k in ("decision", "approach", "note", "requirement", "constraint", "concept",
                                     "explanation", "discovery", "bug", "solution", "question", "reference")}},
    "state": {"root": ("section",),
              "section": ("goal", "task", "blocker", "conflict", "progress", "priority", "next_action", "focus"),
              **{k: () for k in ("goal", "task", "blocker", "conflict", "progress", "priority", "next_action",
                                 "focus")}},
}
TREE_OF = {t: tree for tree, schema in SCHEMAS.items() for t in schema if t != "root"}
GROUP_TYPES = {"topic", "section"}
UNFILED = "unfiled"
# Knowledge kinds declared through the `entry` event (decisions and paths keep their own event kinds).
ENTRY_KINDS = ("requirement", "constraint", "concept", "explanation", "discovery", "bug", "solution", "question",
               "reference")
KNOWLEDGE_TYPES = ("decision", "approach", "note", *ENTRY_KINDS)

STATUSES = {
    "path": ("proposed", "exploring", "selected", "abandoned", "superseded", "reconsidered"),
    "goal": ("active", "achieved", "dropped"),
    "task": ("open", "in_progress", "done", "blocked", "cancelled"),
    "decision": ("proposed", "active", "superseded"),
    "blocker": ("open", "resolved"),
    "conflict": ("open", "resolved"),
    "requirement": ("open", "met", "dropped"),
    "constraint": ("active", "lifted"),
    "concept": ("current", "superseded"),
    "explanation": ("current", "superseded"),
    "discovery": ("current", "superseded", "refuted"),
    "bug": ("open", "fixed", "wontfix", "duplicate"),
    "solution": ("proposed", "applied", "verified", "reverted", "superseded"),
    "question": ("open", "answered", "dropped"),
    "reference": ("current", "superseded"),
}
INITIAL = {"path": "proposed", "goal": "active", "task": "open", "decision": "proposed", "blocker": "open",
           "conflict": "open", "requirement": "open", "constraint": "active", "concept": "current",
           "explanation": "current", "discovery": "current", "bug": "open", "solution": "proposed",
           "question": "open", "reference": "current"}
# Stage 2.9: state items declared through the `state_item` event (goals, tasks and blockers keep their own kinds).
STATE_ITEM_KINDS = ("progress", "priority", "next_action", "focus")
STATUSES.update({"progress": ("current", "superseded"), "priority": ("active", "done", "dropped"),
                 "next_action": ("open", "done", "dropped"), "focus": ("active", "cleared")})
INITIAL.update({"progress": "current", "priority": "active", "next_action": "open", "focus": "active"})
PLANNING_KINDS = {"path", "goal", "task", "blocker", "decision", "conflict"}
# Records with statuses: the log kind, an entry's entry_kind, or a state item's item_kind.
RECORD_KINDS = PLANNING_KINDS | set(ENTRY_KINDS) | set(STATE_ITEM_KINDS)
# The log's event kind -> the node type it creates, and the group or section that holds it.
KIND_NODE = {"path": "approach", "decision": "decision", "goal": "goal", "task": "task", "blocker": "blocker",
             "conflict": "conflict", "note": "note", **{k: k for k in ENTRY_KINDS},
             **{k: k for k in STATE_ITEM_KINDS}}
CONTAINER = {"goal": "state:objectives", "task": "state:tasks", "blocker": "state:blockers",
             "conflict": "state:open_conflicts", "progress": "state:progress", "priority": "state:priorities",
             "next_action": "state:next_actions",
             "focus": "state:working_context"}   # knowledge entries live under topics instead
PATH_ROLES = ("experiment", "accepted", "reverted")
# How a reconciled file change was attributed -> how that attribution is known.
ATTRIBUTION_BASIS = {"agent_tool": "observed", "baseline": "observed", "git_operation": "inferred",
                     "agent_bash": "inferred", "external": "inferred", "unattributed": None}

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY, node_type TEXT NOT NULL, tree TEXT NOT NULL, basis TEXT NOT NULL, label TEXT,
    attrs TEXT NOT NULL, source_event TEXT NOT NULL, log_position INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS edges (
    edge_id INTEGER PRIMARY KEY AUTOINCREMENT, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
    type TEXT NOT NULL, basis TEXT NOT NULL, ord INTEGER, attrs TEXT NOT NULL,
    source_event TEXT NOT NULL, log_position INTEGER NOT NULL, cross_tree INTEGER);
CREATE TABLE IF NOT EXISTS retractions (
    edge_id INTEGER NOT NULL, retracted_by TEXT NOT NULL, reason TEXT, log_position INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS statuses (
    node_id TEXT NOT NULL, status TEXT NOT NULL, reason TEXT, basis TEXT NOT NULL,
    source_event TEXT NOT NULL, log_position INTEGER NOT NULL, at TEXT NOT NULL);
-- Every observed version of every artifact, with how its change was attributed and how that is known.
CREATE TABLE IF NOT EXISTS file_versions (
    version_id TEXT PRIMARY KEY, path TEXT NOT NULL, object_id TEXT, size INTEGER, change TEXT NOT NULL,
    git_blob TEXT, git_commit TEXT, renamed_from TEXT, path_id TEXT, path_role TEXT,
    source_event TEXT NOT NULL, log_position INTEGER NOT NULL, attribution TEXT, attribution_basis TEXT);
CREATE INDEX IF NOT EXISTS idx_versions_path ON file_versions(path, log_position);
-- The files a verification depended on, and the version of each it ran against.
CREATE TABLE IF NOT EXISTS verification_files (
    event_id TEXT NOT NULL, path TEXT NOT NULL, object_id TEXT, log_position INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_vfiles_path ON verification_files(path);
CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_id, type);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_id, type);
CREATE INDEX IF NOT EXISTS idx_edges_cross ON edges(cross_tree, type);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_nodes_tree ON nodes(tree, node_type);
CREATE INDEX IF NOT EXISTS idx_statuses_node ON statuses(node_id);
"""
TABLES = ("nodes", "edges", "retractions", "statuses", "file_versions", "verification_files")
FILE_CHANGES = ("added", "modified", "deleted", "renamed")


def create(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)
    for table in TABLES:
        for action in ("UPDATE", "DELETE"):
            conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_append_only_{action.lower()} BEFORE {action} "
                         f"ON {table} BEGIN SELECT RAISE(ABORT, 'the {table} table is append-only'); END")


def drop(conn: sqlite3.Connection) -> None:
    """Remove the structure tables (only for rebuilding them from the log; the log is never touched)."""
    for table in TABLES:
        for action in ("update", "delete"):
            conn.execute(f"DROP TRIGGER IF EXISTS {table}_append_only_{action}")
        conn.execute(f"DROP TABLE IF EXISTS {table}")


# ------------------------------------------------------------ ids
def root(tree: str) -> str:
    return f"{tree}:"


def session_node(session_id: str) -> str:
    return f"session:{session_id}"


def artifact_node(path: str) -> str:
    return f"artifact:{path}"


file_node = artifact_node   # the name used before format 2


def resolve(node_id: str) -> str:
    """A record id as stored in the log -> the node it names now (legacy `file:` ids become artifacts)."""
    if isinstance(node_id, str) and node_id.startswith("file:"):
        return "artifact:" + node_id[len("file:"):]
    return node_id


# ------------------------------------------------------------ helpers
def _node_exists(conn, node_id: str) -> bool:
    return conn.execute("SELECT 1 FROM nodes WHERE node_id = ?", (node_id,)).fetchone() is not None


def _node_type(conn, node_id: str) -> str | None:
    row = conn.execute("SELECT node_type FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
    return row[0] if row else None


def _tree_of(conn, node_id: str) -> tuple[str, str] | None:
    return conn.execute("SELECT tree, node_type FROM nodes WHERE node_id = ?", (node_id,)).fetchone()


def _add_node(conn, node_id: str, node_type: str, ev: Event, label: str | None = None, parent: str | None = None,
              tree: str | None = None, basis: str = "observed", **attrs) -> bool:
    """Add a node to its tree (under `parent`) unless it exists. Returns True if it was new."""
    if _node_exists(conn, node_id):
        return False
    tree = tree or TREE_OF.get(node_type)
    if tree not in SCHEMAS or node_type not in SCHEMAS[tree]:
        raise SchemaError(f"node type {node_type!r} doesn't belong to any tree")
    if basis not in BASES:
        raise SchemaError(f"basis must be one of {BASES}")
    conn.execute("INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (node_id, node_type, tree, basis, label, canonical_json(attrs), ev.event_id, ev.log_position))
    if parent is not None:
        _add_edge(conn, parent, node_id, "contains", "observed", ev, _next_ord(conn, parent))
    return True


def _add_edge(conn, src: str, dst: str, etype: str, basis: str, ev: Event, ord_: int | None = None, **attrs) -> None:
    a, b = _tree_of(conn, src), _tree_of(conn, dst)
    if etype == "contains":
        if a is None or b is None or a[0] != b[0] or b[1] not in SCHEMAS[a[0]][a[1]]:
            raise SchemaError(f"{src} ({a}) may not contain {dst} ({b})")
    cross = None if a is None or b is None else int(a[0] != b[0])
    conn.execute("INSERT INTO edges (from_id, to_id, type, basis, ord, attrs, source_event, log_position, cross_tree) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (src, dst, etype, basis, ord_, canonical_json(attrs), ev.event_id, ev.log_position, cross))


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
    return [resolve(v) for v in ([value] if isinstance(value, str) else list(value))]


def current_status(conn, node_id: str) -> str | None:
    row = conn.execute("SELECT status FROM statuses WHERE node_id = ? ORDER BY log_position DESC, rowid DESC LIMIT 1",
                       (node_id,)).fetchone()
    return row[0] if row else None


# ------------------------------------------------------------ placing nodes in their trees
def _roots(conn, ev: Event) -> None:
    for tree in TREES:
        _add_node(conn, root(tree), "root", ev, label=tree, tree=tree)


def _container(conn, ev: Event, node_id: str) -> str:
    """A state section, created under the state root on first use."""
    tree, name = node_id.split(":", 1)
    _add_node(conn, node_id, "section", ev, label=name, parent=root(tree))
    return node_id


def topic_path(path: str) -> str:
    """The canonical form of a topic path: lower case, '/' separated, no empty parts ("Auth / JWT" -> "auth/jwt")."""
    return "/".join(p.strip().lower() for p in str(path).replace("\\", "/").split("/") if p.strip())


def topic_node(path: str) -> str:
    return f"topic:{topic_path(path)}"


def _topic(conn, ev: Event, path: str, basis: str = "declared", **attrs) -> str:
    """The node for a topic path, creating it and its parents under the knowledge root on first use."""
    labels = [p.strip() for p in str(path).replace("\\", "/").split("/") if p.strip()]
    canon = topic_path(path)
    if not canon:
        raise SchemaError("a topic needs a name")
    parent = root("knowledge")
    parts = canon.split("/")
    for i in range(len(parts)):
        node = "topic:" + "/".join(parts[: i + 1])
        last = i == len(parts) - 1
        _add_node(conn, node, "topic", ev, label=labels[i], parent=parent, basis=basis,
                  path="/".join(parts[: i + 1]), **(attrs if last else {}))
        parent = node
    return parent


def _session(conn, ev: Event, session_id: str, agent: str | None = None) -> str:
    node = session_node(session_id)
    _add_node(conn, node, "session", ev, label=session_id, parent=root("history"), agent=agent)
    return node


def _artifact(conn, ev: Event, path: str) -> str:
    node = artifact_node(path)
    if _node_exists(conn, node):
        return node
    parts = path.split("/")
    parent = root("artifacts")
    for i in range(len(parts) - 1):
        folder = "/".join(parts[: i + 1])
        _add_node(conn, f"collection:{folder}", "collection", ev, label=parts[i], parent=parent, path=folder)
        parent = f"collection:{folder}"
    _add_node(conn, node, "artifact", ev, label=parts[-1], parent=parent, path=path)
    return node


# ------------------------------------------------------------ validation (before the event is stored)
def validate(conn, kind: str, summary: dict) -> None:
    """Reject a declared operation that can't be applied, so no event is stored for it."""
    op = summary.get("op")
    if kind == "entry":
        if summary.get("entry_kind") not in ENTRY_KINDS:
            raise SchemaError(f"an entry's entry_kind must be one of {ENTRY_KINDS}")
        kind = summary["entry_kind"]
    if kind == "state_item":
        if summary.get("item_kind") not in STATE_ITEM_KINDS:
            raise SchemaError(f"a state item's item_kind must be one of {STATE_ITEM_KINDS}")
        kind = summary["item_kind"]
        if summary.get("rank") is not None and not isinstance(summary["rank"], int):
            raise SchemaError("a priority's rank is an integer (1 is highest)")
    if kind == "topic":
        if op != "create" or not topic_path(summary.get("path") or ""):
            raise SchemaError("a topic event needs op 'create' and a path")
        return
    if kind in RECORD_KINDS:
        node_type = KIND_NODE[kind]
        if op not in ("create", "status"):
            raise SchemaError(f"a {kind} event needs op 'create' or 'status'")
        status = summary.get("status")
        if status is not None and status not in STATUSES[kind]:
            raise SchemaError(f"{kind} status {status!r} must be one of {STATUSES[kind]}")
        if op == "create" and not (summary.get("title") or summary.get("topic")):
            raise SchemaError(f"creating a {kind} needs a title (or, for a path, a topic)")
        if op == "status":
            target = summary.get("id")
            if not target or _node_type(conn, target) != node_type:
                raise SchemaError(f"no {kind} with id {target!r}")
            if status is None:
                raise SchemaError("a status change needs a status")
        for ref in ("alternative_to", "supersedes"):
            for target in _ids(summary.get(ref)):
                if _node_type(conn, target) != node_type:
                    raise SchemaError(f"{ref} must name existing {kind} records; {target!r} isn't one")
        for target in _ids(summary.get("fixes")):
            if _node_type(conn, target) != "bug":
                raise SchemaError(f"fixes must name existing bug records; {target!r} isn't one")
        for topic in [summary.get("topic"), *_ids(summary.get("filed_under"))]:
            if topic is not None and not topic_path(topic):
                raise SchemaError("a topic needs a name")
    elif kind == "relation":
        if summary.get("type") not in EDGE_TYPES or summary.get("type") == "contains":
            raise SchemaError(f"relation type must be one of {sorted(EDGE_TYPES - {'contains'})}")
        if summary.get("basis", "declared") not in ("declared", "inferred"):
            raise SchemaError("a relation event's basis is 'declared' or 'inferred'; 'observed' is the engine's")
        for end in ("from", "to"):
            if not summary.get(end) or not _node_exists(conn, resolve(summary[end])):
                raise SchemaError(f"relation '{end}' must name an existing record")
    elif kind == "retraction":
        edge = summary.get("edge_id")
        row = conn.execute("SELECT type FROM edges WHERE edge_id = ?", (edge,)).fetchone() \
            if isinstance(edge, int) else None
        if row is None:
            raise SchemaError("a retraction names an existing edge_id")
        if row[0] == "contains":
            raise SchemaError("tree structure is observed and can't be retracted; retract a relationship instead")
    if kind == "file_change" and summary.get("change") not in (None, *FILE_CHANGES):
        raise SchemaError(f"file_change change must be one of {FILE_CHANGES}")
    path = summary.get("path_id")
    if path is not None and _node_type(conn, path) != "approach":
        raise SchemaError(f"path_id {path!r} is not a development path")
    role = summary.get("path_role")
    if role is not None and role not in PATH_ROLES:
        raise SchemaError(f"path_role must be one of {PATH_ROLES}")


# ------------------------------------------------------------ apply
def apply(conn, ev: Event, strict: bool = True) -> None:
    """Add one event to the structure.

    Writes are strict: an event that doesn't fit raises, and the write is
    refused. Replays (rebuild, recovery) aren't. A record damaged after it
    was written, which only tampering or disk corruption can cause and which
    `verify` reports, keeps its place in the history tree but adds nothing
    else, so a replay never stops halfway.
    """
    s = ev.summary_fields
    _roots(conn, ev)
    session = _session(conn, ev, ev.session_id, ev.agent)

    # The event's place in the history tree: a user message opens a turn; other events join the current turn.
    if ev.kind == "user_message":
        n = _next_ord(conn, session)
        turn = f"turn:{ev.session_id}:{n}"
        _add_node(conn, turn, "turn", ev, label=f"turn {n}")
        _add_edge(conn, session, turn, "contains", "observed", ev, n)
        parent = turn
    else:
        parent = _current_turn(conn, session) or session
    _add_node(conn, ev.event_id, "event", ev, label=ev.kind, parent=parent, kind=ev.kind)
    if ev.parent_id and _node_exists(conn, ev.parent_id):
        _add_edge(conn, ev.event_id, ev.parent_id, "triggered_by", "observed", ev)
    if strict:
        _by_kind(conn, ev, s, session)
        return
    try:
        _by_kind(conn, ev, s, session)
    except (KeyError, TypeError, ValueError, AttributeError, sqlite3.Error):
        pass


def _by_kind(conn, ev: Event, s: dict, session: str) -> None:
    """What an event adds beyond its place in the history tree, by kind."""
    if ev.kind == "session_start":
        _session_links(conn, ev, session, s)
    if ev.kind in ("file_change", "exclusion") and s.get("path"):
        f = _artifact(conn, ev, s["path"])
        _add_edge(conn, ev.event_id, f, "modifies", "observed", ev)
        if ev.kind == "file_change":
            _file_version(conn, ev, s, f)
    if ev.kind == "verification":
        for target in _ids(s.get("verifies")):
            if _node_exists(conn, target):
                _add_edge(conn, ev.event_id, target, "verifies", "observed", ev)
        for rel_path, object_id in sorted((s.get("relevant_files") or {}).items()):
            conn.execute("INSERT INTO verification_files VALUES (?, ?, ?, ?)",
                         (ev.event_id, rel_path, object_id, ev.log_position))
    if s.get("path_id"):
        _add_edge(conn, ev.event_id, s["path_id"], "part_of", "observed", ev, role=s.get("path_role"))
    if s.get("group") and _node_exists(conn, s["group"]):
        _add_edge(conn, ev.event_id, s["group"], "part_of", "observed", ev)

    if ev.kind in PLANNING_KINDS or ev.kind in ("entry", "state_item"):
        _planning(conn, ev, s)
    elif ev.kind == "topic":
        _topic(conn, ev, s["path"], description=s.get("description"))
    elif ev.kind == "note":
        node = f"note:{ev.event_id}"
        _add_node(conn, node, "note", ev, label=s.get("title") or s.get("text", "")[:80],
                  parent=_topic(conn, ev, s.get("topic") or UNFILED, "declared" if s.get("topic") else "observed"),
                  basis="declared", note_type=s.get("note_type", "note"), body=s.get("text"))
        _add_edge(conn, node, ev.event_id, "references", "observed", ev)
        _declared_links(conn, ev, node, s)
    elif ev.kind == "relation":
        _add_edge(conn, resolve(s["from"]), resolve(s["to"]), s["type"], s.get("basis", "declared"), ev,
                  reason=s.get("reason"))
    elif ev.kind == "retraction":
        conn.execute("INSERT INTO retractions VALUES (?, ?, ?, ?)",
                     (s["edge_id"], ev.event_id, s.get("reason"), ev.log_position))


def _file_version(conn, ev: Event, s: dict, f: str) -> None:
    """Record the version, link renames, and notice a return to an earlier version."""
    path = s["path"]
    change = s.get("change") or ("deleted" if ev.payload_object is None and s.get("deleted") else "modified")
    attribution = s.get("attribution")
    basis = ATTRIBUTION_BASIS.get(attribution) if attribution else "declared"   # reported by an adapter
    attribution = attribution or "reported"
    previous = conn.execute("SELECT object_id FROM file_versions WHERE path = ? ORDER BY log_position DESC LIMIT 1",
                            (path,)).fetchone()
    conn.execute("INSERT INTO file_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (ev.event_id, path, ev.payload_object, s.get("size"), change, s.get("git_blob"),
                  s.get("git_commit"), s.get("old_path"), s.get("path_id"), s.get("path_role"),
                  ev.event_id, ev.log_position, attribution, basis))
    if s.get("old_path"):
        old = _artifact(conn, ev, s["old_path"])
        _add_edge(conn, f, old, "follows", "observed", ev, link="rename")
    # Back to content this path had before (but not just now): a structural revert signal.
    earlier = None
    if ev.payload_object and previous and previous[0] != ev.payload_object:
        earlier = conn.execute("SELECT source_event FROM file_versions WHERE path = ? AND object_id = ? "
                               "AND version_id != ? ORDER BY log_position DESC LIMIT 1",
                               (path, ev.payload_object, ev.event_id)).fetchone()
    if earlier:
        _add_edge(conn, ev.event_id, earlier[0], "reverts", "observed", ev)
    if earlier or s.get("restores_version"):
        _propose_path(conn, ev, f"revert of {path} to an earlier version", "revert", [ev.event_id])


def _session_links(conn, ev: Event, session: str, s: dict) -> None:
    for key, etype, link in (("resumed_from", "follows", "resume"), ("forked_from", "based_on", "fork")):
        other = s.get(key)
        if other:
            _add_edge(conn, session, _session(conn, ev, other), etype, "observed", ev, link=link)
            if link == "fork":
                _propose_path(conn, ev, f"fork of session {other}", "session_fork", [ev.event_id], session=session)
    for other in _ids(s.get("continues")):
        _add_edge(conn, session, _session(conn, ev, other), "based_on", "observed", ev, link="continues")
    branch = s.get("git_branch")
    if branch:
        seen = conn.execute("SELECT 1 FROM nodes WHERE node_type = 'approach' "
                            "AND json_extract(attrs, '$.git_branch') = ?", (branch,)).fetchone()
        if not seen and branch not in ("main", "master"):
            _propose_path(conn, ev, f"git branch {branch}", "git_branch", [ev.event_id], session=session,
                          git_branch=branch)


def _propose_path(conn, ev: Event, description: str, signal: str, evidence: list[str],
                  session: str | None = None, **attrs) -> None:
    """A structural signal proposes an approach, inferred by a named rule; it doesn't name its topic."""
    node = f"path:{ev.event_id}:{signal}"
    _add_node(conn, node, "approach", ev, label=description, parent=_topic(conn, ev, UNFILED, "observed"),
              basis="inferred", topic=None, description=description, signal=signal, source="inferred",
              rule=f"structural signal: {signal}", **attrs)
    _add_status(conn, node, "proposed", f"structural signal: {signal}", "inferred", ev)
    for e in evidence:
        _add_edge(conn, e, node, "supports", "inferred", ev)
    if session:
        _add_edge(conn, session, node, "part_of", "inferred", ev, role="experiment")


def _planning(conn, ev: Event, s: dict) -> None:
    kind = s["entry_kind"] if ev.kind == "entry" else s["item_kind"] if ev.kind == "state_item" else ev.kind
    node_type = KIND_NODE[kind]
    if s["op"] == "create":
        node = f"{kind}:{ev.event_id}"
        title = s.get("title") or s.get("topic")
        # A conflict is observed by the engine (reconciliation); everything else here is declared.
        basis = "observed" if kind == "conflict" else "declared"
        if node_type in KNOWLEDGE_TYPES:
            home = _topic(conn, ev, s["topic"], "declared") if s.get("topic") else _topic(conn, ev, UNFILED, "observed")
        else:
            home = _container(conn, ev, CONTAINER[node_type])
        _add_node(conn, node, node_type, ev, label=title, parent=home,
                  basis=basis, title=title, topic=s.get("topic"), description=s.get("description"),
                  body=s.get("body"), source=basis, rank=s.get("rank"),
                  concerns=sorted(_ids(s.get("concerns"))) or None)
        if node_type in KNOWLEDGE_TYPES and not s.get("topic"):
            _propose_topic(conn, ev, node, s)
        status = s.get("status") or INITIAL[kind]
        if kind == "decision" and s.get("status") is None and s.get("from_user_message"):
            status = "active"   # agent-declared decisions start as proposed; a user's are active
        _add_status(conn, node, status, s.get("reason"), basis, ev)
        if kind == "conflict" and s.get("event") and _node_exists(conn, s["event"]):
            _add_edge(conn, node, s["event"], "references", "observed", ev)
        _add_edge(conn, node, ev.event_id, "references", "observed", ev)
        _declared_links(conn, ev, node, s)
    else:
        node = s["id"]
        _add_status(conn, node, s["status"], s.get("reason"), "declared", ev)
        _add_edge(conn, node, ev.event_id, "references", "observed", ev)
        if kind == "bug" and s["status"] == "fixed":
            for solution in _ids(s.get("fixed_by")):
                if _node_type(conn, solution) == "solution":
                    _add_edge(conn, solution, node, "fixes", "declared", ev)
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
    for etype in ("advances", "blocks", "blocked_by", "caused_by", "fixes", "discussed_in", "evidence_for"):
        for other in _ids(s.get(etype)):
            if _node_exists(conn, other):
                _add_edge(conn, node, other, etype, "declared", ev)
    for path in _ids(s.get("concerns")):
        target = path if path.startswith("artifact:") else artifact_node(path)
        if _node_exists(conn, target):
            _add_edge(conn, node, target, "concerns", "declared", ev)
    for topic in _ids(s.get("filed_under")):
        _add_edge(conn, node, _topic(conn, ev, topic, "declared"), "filed_under", "declared", ev)


def _propose_topic(conn, ev: Event, node: str, s: dict) -> None:
    """An unfiled entry about an artifact is proposed for the topic named by the artifact's top folder (inferred)."""
    for path in _ids(s.get("concerns")):
        path = path[len("artifact:"):] if path.startswith("artifact:") else path
        first = path.split("/", 1)[0]
        name = first if "/" in path else first.rsplit(".", 1)[0]
        if name and topic_path(name) != UNFILED:
            rule = f"inferred from the artifact {path}"
            _add_edge(conn, node, _topic(conn, ev, name, "inferred", rule=rule), "filed_under", "inferred", ev,
                      rule=rule)
            return


def _alternatives(conn, node: str) -> list[str]:
    rows = conn.execute("SELECT to_id FROM edges WHERE from_id = ? AND type = 'alternative_to' "
                        "UNION SELECT from_id FROM edges WHERE to_id = ? AND type = 'alternative_to'",
                        (node, node)).fetchall()
    return sorted(r[0] for r in rows)


# ------------------------------------------------------------ integrity
def check_trees(conn) -> list[dict]:
    """Every non-root node has exactly one container in its own tree, and every cross flag is right."""
    problems = []
    for node_id, tree, parents in conn.execute(
            "SELECT n.node_id, n.tree, (SELECT COUNT(*) FROM edges e JOIN nodes p ON p.node_id = e.from_id "
            "WHERE e.to_id = n.node_id AND e.type = 'contains' AND p.tree = n.tree) "
            "FROM nodes n WHERE n.node_type != 'root'"):
        if parents != 1:
            problems.append({"type": "tree_shape", "node_id": node_id, "tree": tree, "containers": parents})
    for edge_id, flag, a, b in conn.execute(
            "SELECT e.edge_id, e.cross_tree, f.tree, t.tree FROM edges e "
            "JOIN nodes f ON f.node_id = e.from_id JOIN nodes t ON t.node_id = e.to_id"):
        if flag != int(a != b):
            problems.append({"type": "cross_flag", "edge_id": edge_id})
    return problems


# ------------------------------------------------------------ rebuild (integrity and recovery)
def snapshot(conn) -> dict[str, list]:
    return {t: conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in TABLES}


def rebuild(events) -> dict[str, list]:
    """Structure recomputed from scratch by applying every event in log order."""
    mem = sqlite3.connect(":memory:")
    create(mem)
    for ev in events:
        apply(mem, ev, strict=False)
    return snapshot(mem)
