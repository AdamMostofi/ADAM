"""Navigating the four trees and the links between them (architecture revision 3, sections 4 and 6).

Each tree is entered at its root and walked down, and every listing is
short: a child's id, type, label, status, basis, how many children it has,
and how many cross-tree links it has, counted by tree. Contents only appear
when a node is opened, so an agent can find its way from a root to any
record without knowing an id in advance, and without loading what it
doesn't need.

A tree navigator never wanders into another tree. Cross-tree links are
followed only through `links()`, which says which tree each end is in.
"""
from __future__ import annotations

import json

from agent_memory.structure import SCHEMAS, TREES, artifact_node, current_status, resolve, root

GROUPS = {"knowledge": {"approach": "approaches", "decision": "decisions", "note": "notes"},
          "state": {"goal": "objectives", "task": "tasks", "blocker": "blockers", "conflict": "open_conflicts"}}


def _row(conn, node_id: str):
    return conn.execute("SELECT node_id, node_type, tree, basis, label, attrs FROM nodes WHERE node_id = ?",
                        (node_id,)).fetchone()


def _children(conn, node_id: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT e.to_id FROM edges e LEFT JOIN retractions r ON r.edge_id = e.edge_id "
        "WHERE e.from_id = ? AND e.type = 'contains' AND r.retracted_by IS NULL ORDER BY e.ord, e.edge_id",
        (node_id,))]


def link_counts(conn, node_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for (tree,) in conn.execute(
            "SELECT n.tree FROM edges e JOIN nodes n ON n.node_id = CASE WHEN e.from_id = ? THEN e.to_id "
            "ELSE e.from_id END LEFT JOIN retractions r ON r.edge_id = e.edge_id "
            "WHERE (e.from_id = ? OR e.to_id = ?) AND e.cross_tree = 1 AND r.retracted_by IS NULL",
            (node_id, node_id, node_id)):
        counts[tree] = counts.get(tree, 0) + 1
    return dict(sorted(counts.items()))


def entry(conn, node_id: str) -> dict | None:
    """The short listing form of a node."""
    row = _row(conn, node_id)
    if row is None:
        return None
    node_id, node_type, tree, basis, label, _attrs = row
    return {"id": node_id, "type": node_type, "label": label, "status": current_status(conn, node_id),
            "basis": basis, "children": len(_children(conn, node_id)), "links": link_counts(conn, node_id)}


def open_node(conn, tree: str, node_id: str, depth: int = 1) -> dict | None:
    """A node of this tree with its attributes and `depth` levels of children (as listings)."""
    row = _row(conn, node_id)
    if row is None or row[2] != tree:
        return None
    out = entry(conn, node_id)
    out["attrs"] = json.loads(row[5])
    if depth > 0:
        out["items"] = [open_node(conn, tree, c, depth - 1) if depth > 1 else entry(conn, c)
                        for c in _children(conn, node_id)]
    return out


def links(conn, node_id: str, to_tree: str | None = None, types=None) -> list[dict]:
    """The cross-tree links of a node, each with the other end's tree, type, label and the link's basis."""
    node_id = resolve(node_id)
    types = [types] if isinstance(types, str) else list(types or [])
    out = []
    for edge_id, src, dst, etype, basis, attrs in conn.execute(
            "SELECT e.edge_id, e.from_id, e.to_id, e.type, e.basis, e.attrs FROM edges e "
            "LEFT JOIN retractions r ON r.edge_id = e.edge_id "
            "WHERE (e.from_id = ? OR e.to_id = ?) AND e.cross_tree = 1 AND r.retracted_by IS NULL "
            "ORDER BY e.edge_id", (node_id, node_id)):
        other = dst if src == node_id else src
        o = _row(conn, other)
        if (to_tree and o[2] != to_tree) or (types and etype not in types):
            continue
        out.append({"edge_id": edge_id, "direction": "out" if src == node_id else "in", "type": etype,
                    "basis": basis, "tree": o[2], "node": other, "node_type": o[1], "label": o[4],
                    "attrs": json.loads(attrs)})
    return out


# ------------------------------------------------------------ one navigator per tree
class Tree:
    """Shared navigation; each tree adds the lookups its questions need."""

    name = ""

    def __init__(self, connect):
        self._connect = connect

    def _run(self, fn, *args):
        conn = self._connect()
        try:
            return fn(conn, *args)
        finally:
            conn.close()

    def root(self, depth: int = 1) -> dict:
        """The tree's top level. Its root exists once anything has been recorded."""
        found = self._run(open_node, self.name, root(self.name), depth)
        return found or {"id": root(self.name), "type": "root", "label": self.name, "items": []}

    def open(self, node_id: str, depth: int = 1) -> dict | None:
        return self._run(open_node, self.name, resolve(node_id), depth)

    def links(self, node_id: str, to_tree: str | None = None, types=None) -> list[dict]:
        return self._run(links, node_id, to_tree, types)

    def schema(self) -> dict:
        return {t: list(c) for t, c in SCHEMAS[self.name].items()}


class History(Tree):
    """What happened: sessions, turns, events."""

    name = "history"

    def sessions(self) -> list[dict]:
        return self.root()["items"]

    def session(self, session_id: str, depth: int = 2) -> dict | None:
        return self.open(f"session:{session_id}", depth)


class Artifacts(Tree):
    """What exists or has existed: collections and artifacts, with versions."""

    name = "artifacts"

    def open_path(self, path: str, depth: int = 1) -> dict | None:
        """An artifact by its path, or a collection (folder) by its path."""
        path = path.strip("/")
        return self.open(artifact_node(path), depth) or self.open(f"collection:{path}", depth)

    def versions(self, path: str) -> list[dict]:
        def run(conn):
            return [{"version_id": v, "object_id": o, "size": size, "change": c, "attribution": a,
                     "attribution_basis": b, "event": e}
                    for v, o, size, c, a, b, e in conn.execute(
                        "SELECT version_id, object_id, size, change, attribution, attribution_basis, source_event "
                        "FROM file_versions WHERE path = ? ORDER BY log_position", (path,))]
        return self._run(run)


class Knowledge(Tree):
    """What is known: approaches (development paths), decisions, notes."""

    name = "knowledge"

    def find(self, kind: str | None = None, status: str | None = None) -> list[dict]:
        def run(conn):
            types = [kind] if kind else list(GROUPS["knowledge"])
            out = []
            for t in types:
                for c in _children(conn, f"knowledge:{GROUPS['knowledge'][t]}"):
                    e = entry(conn, c)
                    if status is None or e["status"] == status:
                        out.append(e)
            return out
        return self._run(run)


class State(Tree):
    """What matters now: objectives, tasks, blockers, open conflicts (sections grow in Stage 2.9)."""

    name = "state"

    def section(self, name: str, include_closed: bool = False) -> list[dict]:
        closed = {"achieved", "dropped", "done", "cancelled", "resolved"}

        def run(conn):
            items = [entry(conn, c) for c in _children(conn, f"state:{name}")]
            return [i for i in items if include_closed or i["status"] not in closed]
        return self._run(run)


NAVIGATORS = {"history": History, "artifacts": Artifacts, "knowledge": Knowledge, "state": State}
assert set(NAVIGATORS) == set(TREES)
