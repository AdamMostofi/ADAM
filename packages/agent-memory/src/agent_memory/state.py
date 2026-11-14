"""The Active State tree: what matters now (architecture revision 3, section 4.4).

**Two kinds of item:**
- **Declared items** are records in the state tree (goals, tasks, blockers,
  progress notes, priorities, next actions, working-context focus) and
  constraints from the knowledge tree.
- **Generated items** are computed now from the other trees and never
  stored:
  - open conflicts;
  - verification status;
  - decisions that apply to the current focus;
  - artifacts changed since the last session.

**Every item has:**
- its source (`declared` or `generated`) and its basis;
- its age;
- whether it is stale, and why. A declared item goes stale when an artifact
  it concerns changes after it was last declared, or when it hasn't been
  updated for `stale_after_days`.

**Levels:**

| Level | Contains |
|---|---|
| 0 | One short overview |
| 1 | Objectives, constraints, open conflicts, tasks, blockers, next actions, progress |
| 2 | Priorities, working context, verification |

Each level fits its token budget (a store setting), and items that don't fit
become a count ("+3 more").

**Never raw tool output.** Item text comes only from declared titles and
engine-generated fields (paths, statuses, kinds, commands). Payloads and
tool results are never read here, so stored text can't come back as
instructions in a later session.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from agent_memory.structure import artifact_node

SECTIONS = ("objectives", "progress", "tasks", "blockers", "priorities", "constraints", "open_conflicts",
            "working_context", "verification", "next_actions")
STORED = {"objectives": "goal", "progress": "progress", "tasks": "task", "blockers": "blocker",
          "priorities": "priority", "open_conflicts": "conflict", "working_context": "focus",
          "next_actions": "next_action"}
CLOSED = {"achieved", "dropped", "done", "cancelled", "resolved", "superseded", "cleared", "lifted"}
LEVELS = {1: ("objectives", "constraints", "open_conflicts", "tasks", "blockers", "next_actions", "progress"),
          2: ("priorities", "working_context", "verification")}
DEFAULT_SETTINGS = {"state_budgets": {"0": 200, "1": 1500, "2": 3000}, "stale_after_days": 14,
                    "recent_changes": 20}
TASK_ORDER = {"in_progress": 0, "blocked": 1, "open": 2}


def tokens(text: str) -> int:
    """A token estimate (about 4 characters per token)."""
    return math.ceil(len(text) / 4)


def _when(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class ActiveState:
    def __init__(self, store, now: datetime | None = None, environment: dict | None = None):
        self.store = store
        self.now = now or datetime.now(timezone.utc)
        self.environment = environment
        self.settings = store.settings

    def _conn(self):
        return self.store._connect()

    # ------------------------------------------------------------ declared records
    def _declared(self, conn, node_type: str, section: str) -> list[dict]:
        items = []
        for node_id, label, attrs, pos in conn.execute(
                "SELECT node_id, label, attrs, log_position FROM nodes WHERE node_type = ? ORDER BY log_position",
                (node_type,)).fetchall():
            items.append(self._item(conn, node_id, node_type, section, label, json.loads(attrs), pos))
        return items

    def _item(self, conn, node_id, node_type, section, label, attrs, created_pos) -> dict:
        rows = conn.execute("SELECT status, basis, log_position, at, reason FROM statuses WHERE node_id = ? "
                            "ORDER BY log_position, rowid", (node_id,)).fetchall()
        status, basis, last_pos, last_at, reason = rows[-1] if rows else (None, "declared", created_pos, None, None)
        if not rows:
            last_at = conn.execute("SELECT occurred_at FROM events WHERE log_position = ?", (created_pos,)).fetchone()[0]
        when = _when(last_at)
        age = (self.now - when).total_seconds() / 86400 if when else None
        stale = []
        for (path,) in conn.execute(
                "SELECT substr(e.to_id, 10) FROM edges e WHERE e.from_id = ? AND e.type = 'concerns' "
                "AND e.to_id LIKE 'artifact:%'", (node_id,)).fetchall():
            later = conn.execute("SELECT source_event FROM file_versions WHERE path = ? AND log_position > ? "
                                 "ORDER BY log_position DESC LIMIT 1", (path, last_pos)).fetchone()
            if later:
                stale.append(f"{path} changed in event {later[0]} after this was last updated")
        limit = self.settings["stale_after_days"]
        if age is not None and age > limit and status not in CLOSED:
            stale.append(f"not updated for {int(age)} days (limit {limit})")
        return {"id": node_id, "section": section, "kind": node_type, "label": label, "status": status,
                "reason": reason, "source": "declared", "basis": basis, "rank": attrs.get("rank"),
                "age_days": round(age, 1) if age is not None else None, "stale": bool(stale),
                "stale_reasons": stale}

    # ------------------------------------------------------------ generated items
    def _constraints(self, conn) -> list[dict]:
        return [dict(i, section="constraints") for i in self._declared(conn, "constraint", "constraints")]

    def _changes(self, conn) -> list[dict]:
        boundary = conn.execute("SELECT COALESCE(MAX(log_position), 0) FROM events WHERE kind = 'session_end'"
                                ).fetchone()[0]
        rows = conn.execute("SELECT path, change, attribution, attribution_basis, source_event, MAX(log_position) "
                            "FROM file_versions WHERE log_position > ? GROUP BY path ORDER BY MAX(log_position) DESC",
                            (boundary,)).fetchall()
        return [{"id": artifact_node(path), "section": "progress", "kind": "change",
                 "label": f"{path} {change}" + (f" ({attribution})" if attribution and attribution != "reported" else ""),
                 "status": change, "source": "generated", "basis": basis or "observed", "event": event,
                 "age_days": None, "stale": False, "stale_reasons": []}
                for path, change, attribution, basis, event, _ in rows[: self.settings["recent_changes"]]]

    def _verification(self, conn) -> list[dict]:
        if "software" not in self.store.profiles:
            return []
        latest = {}
        for event_id, summary in conn.execute(
                "SELECT event_id, summary_fields FROM events WHERE kind = 'verification' ORDER BY log_position"):
            s = json.loads(summary)
            latest[(s.get("command"), tuple(s.get("targets") or ()))] = (event_id, s)
        out = []
        for (command, targets), (event_id, s) in latest.items():
            st = self.store.verification_status(event_id, self.environment)
            out.append({"id": event_id, "section": "verification", "kind": "verification",
                        "label": f"{command or 'check'}: {s.get('result')}" + (f" [{', '.join(targets)}]" if targets else ""),
                        "status": st["status"], "source": "generated", "basis": "observed", "age_days": None,
                        "stale": st["status"] == "stale", "stale_reasons": st["reasons"] if st["status"] != "verified" else []})
        return out

    def _applicable_decisions(self, conn, focus: list[dict]) -> list[dict]:
        """Active decisions concerning a focused artifact, or filed under a focused topic."""
        targets = set()
        for f in focus:
            if f["status"] in CLOSED:
                continue
            for (to,) in conn.execute("SELECT to_id FROM edges WHERE from_id = ? AND type IN ('concerns', 'filed_under')",
                                      (f["id"],)):
                targets.add(to)
        if not targets:
            return []
        marks = ",".join("?" * len(targets))
        ids = [r[0] for r in conn.execute(
            f"SELECT DISTINCT n.node_id FROM nodes n JOIN edges e ON e.from_id = n.node_id WHERE n.node_type = 'decision' "
            f"AND e.type IN ('concerns', 'filed_under') AND e.to_id IN ({marks}) "
            f"UNION SELECT DISTINCT e.to_id FROM edges e JOIN nodes n ON n.node_id = e.to_id "
            f"WHERE n.node_type = 'decision' AND e.type = 'contains' AND e.from_id IN ({marks})",
            (*targets, *targets))]
        out = []
        for node_id in ids:
            label, attrs, pos = conn.execute("SELECT label, attrs, log_position FROM nodes WHERE node_id = ?",
                                             (node_id,)).fetchone()
            item = self._item(conn, node_id, "decision", "working_context", label, json.loads(attrs), pos)
            if item["status"] == "active":
                out.append(dict(item, source="generated", reason="applies to the current focus"))
        return out

    # ------------------------------------------------------------ sections
    def section(self, name: str, include_closed: bool = False) -> list[dict]:
        if name not in SECTIONS:
            raise KeyError(f"unknown section {name!r}; sections: {SECTIONS}")
        conn = self._conn()
        try:
            if name == "constraints":
                items = self._constraints(conn)
            elif name == "verification":
                items = self._verification(conn)
            else:
                items = self._declared(conn, STORED[name], name)
                if name == "progress":
                    items = items + self._changes(conn)
                if name == "working_context":
                    items = items + self._applicable_decisions(conn, items)
        finally:
            conn.close()
        if not include_closed:
            items = [i for i in items if i["status"] not in CLOSED]
        return _order(name, items)

    def item(self, item_id: str) -> dict | None:
        """One item, expanded: its full record and its links to evidence in every tree."""
        node = self.store.node(item_id)
        if node is None:
            return None
        links = self.store.links(item_id)
        evidence = {}
        for link in links:
            evidence.setdefault(link["tree"], []).append(
                {"id": link["node"], "type": link["type"], "basis": link["basis"], "label": link["label"],
                 "direction": link["direction"]})
        found = None
        for name in SECTIONS:
            for i in self.section(name, include_closed=True):
                if i["id"] == item_id:
                    found = i
                    break
            if found:
                break
        return {"item": found, "record": {k: node[k] for k in ("id", "type", "tree", "basis", "label", "status",
                                                                  "status_history")},
                "evidence": evidence}

    # ------------------------------------------------------------ levels
    def overview(self, budget: int | None = None) -> dict:
        """Level 0: one short paragraph."""
        budget = budget or self.settings["state_budgets"]["0"]
        counts = {name: len(self.section(name)) for name in SECTIONS}
        stale = sum(1 for name in SECTIONS for i in self.section(name) if i["stale"])
        objectives = self.section("objectives")
        tasks = self.section("tasks")
        nxt = self.section("next_actions")
        parts = []
        if objectives:
            parts.append(f"Objective: {objectives[0]['label']}" + (f" (+{len(objectives) - 1} more)"
                                                                     if len(objectives) > 1 else "") + ".")
        blocked = sum(1 for t in tasks if t["status"] == "blocked")
        parts.append(f"Tasks: {len(tasks)} open" + (f" ({blocked} blocked)" if blocked else "") + ".")
        for name, word in (("blockers", "Blockers"), ("open_conflicts", "Conflicts"), ("constraints", "Constraints")):
            if counts[name]:
                parts.append(f"{word}: {counts[name]}.")
        checks = {}
        for v in self.section("verification"):
            checks[v["status"]] = checks.get(v["status"], 0) + 1
        if checks:
            parts.append("Checks: " + ", ".join(f"{n} {s}" for s, n in sorted(checks.items())) + ".")
        if stale:
            parts.append(f"Stale items: {stale}.")
        if nxt:
            parts.append(f"Next: {nxt[0]['label']}.")
        text = _fit(" ".join(parts), budget)
        return {"level": 0, "text": text, "tokens": tokens(text), "budget": budget, "counts": counts}

    def level(self, n: int, budget: int | None = None) -> dict:
        """Level 1 or 2: the level's sections as short lines, within the budget."""
        if n == 0:
            return self.overview(budget)
        budget = budget or self.settings["state_budgets"][str(n)]
        lines, omitted, used = [], {}, 0
        for name in LEVELS[n]:
            items = self.section(name)
            if not items:
                continue
            header = f"## {name.replace('_', ' ')}"
            if used + tokens(header) > budget:
                omitted[name] = len(items)
                continue
            lines.append(header)
            used += tokens(header) + 1
            for k, i in enumerate(items):
                line = _line(i)
                rest = len(items) - k - 1
                tail = f"  (+{rest} more)" if rest else ""
                if used + tokens(line) + tokens(tail) + 1 > budget:
                    more = f"  (+{len(items) - k} more)"
                    lines.append(more)
                    used += tokens(more) + 1
                    omitted[name] = len(items) - k
                    break
                lines.append(line)
                used += tokens(line) + 1
        text = "\n".join(lines)
        return {"level": n, "text": text, "tokens": tokens(text), "budget": budget, "omitted": omitted}


def _order(name: str, items: list[dict]) -> list[dict]:
    if name == "priorities":
        return sorted(items, key=lambda i: (i.get("rank") is None, i.get("rank") or 0))
    if name == "tasks":
        return sorted(items, key=lambda i: TASK_ORDER.get(i["status"], 9))
    return items


def _line(item: dict) -> str:
    meta = [item["status"]] if item["status"] else []
    if item.get("age_days") is not None:
        meta.append(f"{item['age_days']:g}d")
    if item["source"] == "generated":
        meta.append("generated")
    if item["basis"] == "inferred":
        meta.append("inferred")
    text = f"- [{item['id']}] {item['label']} ({', '.join(meta)})"
    if item["stale"]:
        text += f" STALE: {item['stale_reasons'][0]}"
    return text


def _fit(text: str, budget: int) -> str:
    if tokens(text) <= budget:
        return text
    return text[: max(0, budget * 4 - 3)].rstrip() + "..."
