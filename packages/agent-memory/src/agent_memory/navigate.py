"""Navigating the historical tree and the relationship graph (design section 6.1).

Every edge returned carries its `type` and its `basis` (`recorded`,
`declared` or `inferred`), so an inferred link is never presented as
observed. Retracted edges are left out of navigation by default, and are
still visible with `include_retracted=True`. Nothing is ever deleted.
"""
from __future__ import annotations

import json
import sqlite3
from collections import deque

from agent_memory.structure import current_status, file_node, session_node


def _edge(row) -> dict:
    edge_id, src, dst, etype, basis, ord_, attrs, source_event, pos, retracted_by = row
    return {"edge_id": edge_id, "from": src, "to": dst, "type": etype, "basis": basis, "ord": ord_,
            "attrs": json.loads(attrs), "source_event": source_event, "retracted_by": retracted_by}


EDGE_SQL = ("SELECT e.edge_id, e.from_id, e.to_id, e.type, e.basis, e.ord, e.attrs, e.source_event, e.log_position, "
            "r.retracted_by FROM edges e LEFT JOIN retractions r ON r.edge_id = e.edge_id")


def edges(conn, node_id: str, direction: str = "out", types=None, include_retracted: bool = False) -> list[dict]:
    clauses, args = [], []
    if direction in ("out", "both"):
        clauses.append("e.from_id = ?"); args.append(node_id)
    if direction in ("in", "both"):
        clauses.append("e.to_id = ?"); args.append(node_id)
    sql = f"{EDGE_SQL} WHERE ({' OR '.join(clauses)})"
    if types:
        types = [types] if isinstance(types, str) else list(types)
        sql += f" AND e.type IN ({','.join('?' * len(types))})"
        args += types
    if not include_retracted:
        sql += " AND r.retracted_by IS NULL"
    return [_edge(r) for r in conn.execute(sql + " ORDER BY e.ord IS NULL, e.ord, e.edge_id", args)]


def node(conn, node_id: str, include_retracted: bool = False) -> dict | None:
    row = conn.execute("SELECT node_id, node_type, label, attrs, source_event FROM nodes WHERE node_id = ?",
                       (node_id,)).fetchone()
    if row is None:
        return None
    history = [{"status": s, "reason": r, "basis": b, "source_event": e, "at": at}
               for s, r, b, e, at in conn.execute(
                   "SELECT status, reason, basis, source_event, at FROM statuses WHERE node_id = ? "
                   "ORDER BY log_position, rowid", (node_id,))]
    return {"id": row[0], "type": row[1], "label": row[2], "attrs": json.loads(row[3]), "source_event": row[4],
            "status": history[-1]["status"] if history else None, "status_history": history,
            "out": edges(conn, node_id, "out", include_retracted=include_retracted),
            "in": edges(conn, node_id, "in", include_retracted=include_retracted)}


def children(conn, node_id: str) -> list[str]:
    return [e["to"] for e in edges(conn, node_id, "out", "contains")]


def tree(conn, node_id: str = "project", depth: int = 2) -> dict:
    """The tree below a node, to `depth` levels, in recorded order."""
    n = node(conn, node_id)
    out = {"id": node_id, "type": n["type"] if n else None, "label": n["label"] if n else None}
    if depth > 0:
        out["children"] = [tree(conn, c, depth - 1) for c in children(conn, node_id)]
    return out


def trace(conn, start: str, types=None, direction: str = "out", depth: int = 6) -> list[dict]:
    """Follow relationships from a record, breadth first. Returns the edges walked, each with its basis."""
    walked, seen, queue = [], {start}, deque([(start, 0)])
    while queue:
        current, d = queue.popleft()
        if d >= depth:
            continue
        for e in edges(conn, current, direction, types):
            if e["type"] == "contains":
                continue
            nxt = e["to"] if e["from"] == current else e["from"]
            walked.append({**e, "depth": d + 1})
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, d + 1))
    return walked


def _of_type(conn, ids, node_type: str) -> list[str]:
    ids = list(ids)
    if not ids:
        return []
    rows = conn.execute(f"SELECT node_id FROM nodes WHERE node_type = ? AND node_id IN ({','.join('?' * len(ids))})",
                        [node_type, *ids]).fetchall()
    found = {r[0] for r in rows}
    return [i for i in ids if i in found]


def _kind(conn, event_id: str) -> str | None:
    row = conn.execute("SELECT json_extract(attrs, '$.kind') FROM nodes WHERE node_id = ?", (event_id,)).fetchone()
    return row[0] if row else None


def _session_events(conn, session: str) -> list[str]:
    out = []
    for child in children(conn, session):
        if child.startswith("turn:"):
            out.extend(children(conn, child))
        else:
            out.append(child)
    return out


# ------------------------------------------------------------ the navigations of design 6.1
def project(conn) -> dict:
    nodes = lambda t: [r[0] for r in conn.execute("SELECT node_id FROM nodes WHERE node_type = ? ORDER BY rowid", (t,))]
    return {"sessions": children(conn, "project"), "paths": nodes("path"), "goals": nodes("goal"),
            "decisions": nodes("decision")}


def session(conn, session_id: str) -> dict:
    sid = session_node(session_id)
    events = _session_events(conn, sid)
    worked_on = {e["to"] for ev in events + [sid] for e in edges(conn, ev, "out", "part_of")}
    links = [e for e in edges(conn, sid, "out", ("follows", "based_on"))]
    return {"turns": [c for c in children(conn, sid) if c.startswith("turn:")],
            "events": events, "paths": sorted(worked_on),
            "continued_from": [e["to"] for e in links if e["attrs"].get("link") in ("resume", "continues")],
            "forked_from": [e["to"] for e in links if e["attrs"].get("link") == "fork"],
            "links": links}


def event(conn, event_id: str) -> dict:
    caused = [e["from"] for e in edges(conn, event_id, "in", ("triggered_by", "caused_by", "in_response_to"))]
    return {"files": [e["to"] for e in edges(conn, event_id, "out", "modifies")],
            "verifications": [e["from"] for e in edges(conn, event_id, "in", "verifies")
                              if _kind(conn, e["from"]) == "verification"],
            "triggered_by": [e["to"] for e in edges(conn, event_id, "out", ("triggered_by", "caused_by",
                                                                                "in_response_to"))],
            "caused": caused}


def file(conn, path: str) -> dict:
    f = file_node(path)
    changes = [e["from"] for e in edges(conn, f, "in", "modifies")]
    versions = [{"version_id": v, "object_id": o, "size": size, "change": c, "git_blob": b, "git_commit": gc,
                 "renamed_from": rf, "path_id": pid, "path_role": role, "event": e}
                for v, o, size, c, b, gc, rf, pid, role, e in conn.execute(
                    "SELECT version_id, object_id, size, change, git_blob, git_commit, renamed_from, path_id, "
                    "path_role, source_event FROM file_versions WHERE path = ? ORDER BY log_position", (path,))]
    covered_by = [r[0] for r in conn.execute(
        "SELECT event_id FROM verification_files WHERE path = ? ORDER BY log_position", (path,))] \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'verification_files'").fetchone() else []
    return {"changes": changes, "versions": versions,
            "verifications": [e["from"] for e in edges(conn, f, "in", ("verifies", "tests"))] + covered_by}


def decision(conn, decision_id: str) -> dict:
    n = node(conn, decision_id)
    return {"status": n["status"], "status_history": n["status_history"],
            "discussion": [e["to"] for e in n["out"] if e["type"] in ("based_on", "references")],
            "evidence": [e["from"] for e in n["in"] if e["type"] == "supports"],
            "alternatives": sorted({e["to"] for e in n["out"] if e["type"] == "alternative_to"}
                                   | {e["from"] for e in n["in"] if e["type"] == "alternative_to"}),
            "replaced_by": [e["from"] for e in n["in"] if e["type"] == "supersedes"],
            "replaces": [e["to"] for e in n["out"] if e["type"] == "supersedes"]}


def verification(conn, event_id: str, summary: dict) -> dict:
    # Commit, environment and relevant files are recorded in Stage 2.4; the event's fields hold what is known now.
    return {"command": summary.get("command"), "result": summary.get("result"), "exit_code": summary.get("exit_code"),
            "verifies": [e["to"] for e in edges(conn, event_id, "out", "verifies")],
            "triggered_by": [e["to"] for e in edges(conn, event_id, "out", "triggered_by")]}


def path(conn, path_id: str) -> dict:
    n = node(conn, path_id)
    members = [e for e in n["in"] if e["type"] == "part_of"]
    return {"topic": n["attrs"].get("topic"), "description": n["attrs"].get("description"),
            "source": n["attrs"].get("source"), "status": n["status"], "status_history": n["status_history"],
            "reason": n["status_history"][-1]["reason"] if n["status_history"] else None,
            "alternatives": sorted({e["to"] for e in n["out"] if e["type"] == "alternative_to"}
                                   | {e["from"] for e in n["in"] if e["type"] == "alternative_to"}),
            "evidence": [e["from"] for e in n["in"] if e["type"] == "supports"],
            "abandoned_because": [e["to"] for e in n["out"] if e["type"] == "abandoned_because"],
            "selected_over": [e["to"] for e in n["out"] if e["type"] == "selected_over"],
            "attempts": [{"record": e["from"], "role": e["attrs"].get("role")} for e in members]}


def status_of(conn, node_id: str) -> str | None:
    return current_status(conn, node_id)
