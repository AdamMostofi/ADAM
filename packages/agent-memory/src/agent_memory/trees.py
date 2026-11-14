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

from agent_memory.structure import (KNOWLEDGE_TYPES, SCHEMAS, TREES, artifact_node, current_status, resolve, root,
                                     topic_node, topic_path)


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

    def __init__(self, connect, store=None):
        super().__init__(connect)
        self._store = store

    def search(self, query: str, limit: int = 20, session_id: str | None = None) -> list[dict]:
        """Full-text search over conversation text (messages and compactions), newest index first by rank."""
        return self._store.search_index.history(query, limit, session_id)

    def sessions(self) -> list[dict]:
        return self.root()["items"]

    def session(self, session_id: str, depth: int = 2) -> dict | None:
        return self.open(f"session:{session_id}", depth)


class Artifacts(Tree):
    """What exists or has existed: collections and artifacts, with versions, parts and dependencies.

    Parts (code symbols, document sections), dependencies, metadata and search
    come from the derived artifact index, which is brought up to date
    (incrementally) before each lookup that needs it.
    """

    name = "artifacts"

    def __init__(self, connect, store=None):
        super().__init__(connect)
        self._store = store

    def _index(self):
        self._store.update_artifacts()
        return self._store.codegraph

    def _current(self, path: str) -> str | None:
        found = self._store.current_files().get(path)
        return found[0] if found else None

    def open(self, node_id: str, depth: int = 1) -> dict | None:
        node = super().open(node_id, depth)
        if node and node["type"] == "artifact" and self._store is not None:
            path = node["attrs"]["path"]
            oid = self._current(path)
            index = self._index()
            node["present"] = oid is not None
            node["metadata"] = index.metadata(oid) if oid else None
            node["parts"] = len(index.parts(path))
        return node

    def parts(self, path: str) -> list[dict]:
        """Symbols or sections of an artifact, in order, with line ranges and parents."""
        return self._index().parts(path)

    def find_part(self, name: str, kind: str | None = None) -> list[dict]:
        """Where is it? Parts by name or qualified name ("append", "Store.append", "Usage"), in every artifact."""
        return self._index().find_part(name, kind)

    def depends(self, path: str, direction: str = "dependencies", closure: bool = False) -> dict:
        """What an artifact uses (imports, links), or what uses it, with external and unresolved references."""
        index = self._index()
        types = ("imports", "links")
        if closure:
            found = sorted(index.closure([path], direction, types) - {path})
        elif direction == "dependencies":
            found = sorted(set(index.imports_of(path)) | set(index.links_of(path)))
        else:
            found = sorted(set(index.importers_of(path)) | set(index.linked_from(path)))
        out = {"path": path, "direction": direction, "artifacts": found}
        if direction == "dependencies" and not closure:
            out["external"] = index.external_imports(path)
            out["unresolved"] = index.unresolved([path]).get(path, [])
        return out

    def metadata(self, path: str) -> dict | None:
        oid = self._current(path)
        return self._index().metadata(oid) if oid else None

    def at(self, path: str, version=-1, max_bytes: int | None = None) -> dict:
        """The content of one version: by index (-1 is the latest) or by version id. Bounded by `max_bytes`."""
        versions = self.versions(path)
        if not versions:
            raise KeyError(f"no versions of {path}")
        chosen = versions[version] if isinstance(version, int) else \
            next((v for v in versions if v["version_id"] == version), None)
        if chosen is None:
            raise KeyError(f"{path} has no version {version!r}")
        if chosen["object_id"] is None:
            return {**chosen, "content": None, "truncated": False}
        data = self._store.archive.get(chosen["object_id"])
        cut = max_bytes is not None and len(data) > max_bytes
        return {**chosen, "content": data[:max_bytes] if cut else data, "truncated": cut}

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search over current text artifacts (permitted content only)."""
        return self._index().search(query, limit)

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
    """What is known: a topic hierarchy of entries (decisions, approaches, requirements, bugs, solutions ...).

    Browsing returns listings only: an entry's body appears only when the
    entry itself is opened.
    """

    name = "knowledge"

    def __init__(self, connect, store=None):
        super().__init__(connect)
        self._store = store

    def topics(self, depth: int = 1) -> dict:
        """The topic hierarchy from the root, `depth` levels down."""
        return self.root(depth)

    def topic(self, path: str, depth: int = 1) -> dict | None:
        return self.open(topic_node(path), depth)

    def find(self, kind: str | None = None, status: str | None = None, topic: str | None = None,
             text: str | None = None, limit: int = 100) -> list[dict]:
        """Entries by kind, status, topic (home or filed under, subtopics included) and text, as listings."""
        def run(conn):
            types = [kind] if kind else list(KNOWLEDGE_TYPES)
            sql = (f"SELECT node_id FROM nodes WHERE tree = 'knowledge' AND node_type IN "
                   f"({','.join('?' * len(types))})")
            args: list = list(types)
            if topic:
                within = _topics_within(conn, topic)
                if not within:
                    return []
                marks = ",".join("?" * len(within))
                sql += (f" AND node_id IN (SELECT e.to_id FROM edges e WHERE e.type = 'contains' AND e.from_id IN "
                        f"({marks}) UNION SELECT e.from_id FROM edges e LEFT JOIN retractions r ON "
                        f"r.edge_id = e.edge_id WHERE e.type = 'filed_under' AND r.retracted_by IS NULL "
                        f"AND e.to_id IN ({marks}))")
                args += within + within
            ids = [r[0] for r in conn.execute(sql + " ORDER BY log_position", args)]
            if text:
                ranked = [r[0] for r in self._store.search_index.knowledge(text, limit=10_000)]
                keep = set(ids)
                ids = [i for i in ranked if i in keep]
            out = []
            for node_id in ids:
                e = entry(conn, node_id)
                if status is None or e["status"] == status:
                    out.append(e)
                if len(out) >= limit:
                    break
            return out
        return self._run(run)

    def history_of(self, entry_id: str) -> dict | None:
        """An entry's whole story: statuses, what it replaced and what replaced it, evidence, fixes, and origins."""
        def run(conn):
            from agent_memory.navigate import node as full
            n = full(conn, entry_id)
            if n is None or n["tree"] != "knowledge":
                return None

            def chain(start: str, etype: str, direction: str) -> list[str]:
                out, current = [], start
                while True:
                    nxt = [e["to"] if direction == "out" else e["from"]
                           for e in (full(conn, current)["out"] if direction == "out" else full(conn, current)["in"])
                           if e["type"] == etype]
                    nxt = [x for x in nxt if x not in out and x != start]
                    if not nxt:
                        return out
                    out.append(nxt[0])
                    current = nxt[0]

            def ends(edges, etype, key):
                return [{"id": e[key], "basis": e["basis"], "tree": _row(conn, e[key])[2] if _row(conn, e[key]) else None}
                        for e in edges if e["type"] == etype]
            return {"id": n["id"], "kind": n["type"], "title": n["label"], "body": n["attrs"].get("body"),
                    "status": n["status"], "status_history": n["status_history"], "basis": n["basis"],
                    "replaces": chain(entry_id, "supersedes", "out"),
                    "replaced_by": chain(entry_id, "supersedes", "in"),
                    "evidence": ends(n["in"], "supports", "from"),
                    "fixes": ends(n["out"], "fixes", "to"), "fixed_by": ends(n["in"], "fixes", "from"),
                    "based_on": ends(n["out"], "based_on", "to"),
                    "discussed_in": ends(n["out"], "discussed_in", "to"),
                    "concerns": ends(n["out"], "concerns", "to"),
                    "topics": [e["from"] for e in n["in"] if e["type"] == "contains"]
                              + [e["to"] for e in n["out"] if e["type"] == "filed_under"],
                    "declared_in": [e["to"] for e in n["out"] if e["type"] == "references"]}
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


def _topics_within(conn, topic: str) -> list[str]:
    """A topic and all its subtopics."""
    canon = topic_path(topic)
    return [r[0] for r in conn.execute(
        "SELECT node_id FROM nodes WHERE node_type = 'topic' AND (node_id = ? OR node_id LIKE ? ESCAPE '\\')",
        (f"topic:{canon}", "topic:" + canon.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"))]


NAVIGATORS = {"history": History, "artifacts": Artifacts, "knowledge": Knowledge, "state": State}
assert set(NAVIGATORS) == set(TREES)
