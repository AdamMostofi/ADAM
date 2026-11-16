"""The dynamic context manager (architecture revision 3, section 7).

It decides which memory goes into an agent's context, at what level of
detail, and what is replaced by a short reference line. It keeps a durable
record of those choices so they can be restored.

**The ledger.** Every decision is an event in the log:
- `context_load`, `context_offload`, `context_restore`, `context_pin`, `context_reset`;
- they are written under the agent's session id, with writer `context-manager`.

A session's working set is rebuilt from those events. It survives crashes and
appears in checkpoints, because it is the log, and history can answer "what
did the agent know when it decided X?".

**Packets.** A packet is one piece of delivered context:
- a record of a tree at a level;
- a state view (`state:overview`, `state:level1`, `state:level2`, `state:<section>`);
- a tool result.

Its exact text is archived (compressed, encrypted, deduplicated), so
`restore` returns exactly what was offloaded, plus a note when the record has
changed since.

**Budget.** The total budget is a setting, split by tree (shares).
- A load that would go over budget evicts, in order: items in trees over
  their share first, then P3, P2 and P1; least recently used and largest
  first.
- P0 items and pinned items are never evicted automatically.
- What still doesn't fit is delivered as a reference line instead.

So the context the engine delivers never exceeds its budget.

**Priorities:**

| Priority | Contents |
|---|---|
| P0 | Constraints, active objectives, open conflicts, in-progress or blocked tasks, open blockers, pinned items |
| P1 | What the agent asked for |
| P2 | Missing-context offers and supporting records |
| P3 | History |

**Relevance** is deterministic, with no model involved. It is scored from:
- explicit mentions (ids, paths, symbol names, topic names);
- full-text matches;
- status.

Reasons are kept with every offer.

**What the engine can't do:** it can't remove tokens from a context window
that the agent controls. `request_context()` is for clients that assemble
every request themselves (tier A). `delta()` is for hook-based clients that
add context per prompt and after compaction (tier B). Tool results serve
tool-only clients (tier C). See section 7.5 and section 11 of the
architecture.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from agent_memory.schema import EventInput
from agent_memory.state import tokens as estimate_tokens

CONTEXT_KINDS = ("context_load", "context_offload", "context_restore", "context_pin", "context_reset")
WRITER = "context-manager"
PRIORITIES = ("P0", "P1", "P2", "P3")
TREES = ("state", "knowledge", "artifacts", "history")
HEADER_RESERVE = 40   # tokens kept free for the bundle's heading, so a delivered bundle never exceeds the budget
DEFAULT_CONTEXT = {"budget": 12000, "packet_max": 2000,
                   "shares": {"state": 0.30, "knowledge": 0.25, "artifacts": 0.25, "history": 0.20}}
ID_PATTERN = re.compile(r"\b(?:bug|solution|decision|path|requirement|constraint|concept|explanation|discovery|"
                        r"question|reference|goal|task|blocker|conflict|progress|priority|next_action|focus|note|"
                        r"topic|artifact|session):[\w./:-]+")
PATH_PATTERN = re.compile(r"(?<![\w/])[\w.-]+(?:/[\w.-]+)+|\b[\w-]+\.(?:py|ts|tsx|js|jsx|md|rst|json|toml|yaml|yml|txt|sql|sh)\b")
WORD_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\b")
STOPWORDS = frozenset("""a an and are as at be but by can do does for from has have how i if in into is it its
me my no not of on or our so than that the their them then there these this to up us was we were what when
where which while who why will with you your should would could please fix add make use check find look need
want also just about again some more most other only same any all each""".split())


class ContextError(ValueError):
    """A context operation that isn't allowed (for example, an automatic offload of a P0 item)."""


@dataclass
class Item:
    handle: str
    ref: dict
    level: int
    tokens: int
    priority: str
    tree: str
    label: str
    reason: str
    object_id: str | None
    text_hash: str
    state: str = "loaded"            # loaded | offloaded
    pinned: bool = False
    keep: str | None = None
    last_used: int = 0
    history: list = field(default_factory=list)

    def reference(self) -> str:
        """The one-line stand-in for an offloaded item (about 20 tokens)."""
        line = f"[{self.handle}] {self.label} ({self.tree}) - offloaded; mem_restore {self.handle}"
        return line + (f"; kept: {self.keep}" if self.keep else "")


class ContextManager:
    def __init__(self, store, tokenizer=None):
        self.store = store
        self.count = tokenizer or estimate_tokens
        self._override: int | None = None   # a smaller budget for one delivery (an agent's injection cap)

    # ------------------------------------------------------------ settings
    @property
    def settings(self) -> dict:
        merged = json.loads(json.dumps(DEFAULT_CONTEXT))
        mine = self.store.settings.get("context") or {}
        for key, value in mine.items():
            if isinstance(value, dict):
                merged[key].update(value)
            else:
                merged[key] = value
        return merged

    def budget(self) -> int:
        full = int(self.settings["budget"])
        return min(full, self._override) if self._override else full

    def share(self, tree: str) -> int:
        return int(self.budget() * float(self.settings["shares"].get(tree, 0)))

    # ------------------------------------------------------------ the ledger (rebuilt from the log)
    def ledger(self, session_id: str) -> dict[str, Item]:
        items: dict[str, Item] = {}
        for ev in self.store.events(session_id=session_id):
            if ev.kind not in CONTEXT_KINDS:
                continue
            s = ev.summary_fields
            if ev.kind == "context_load":
                items[s["handle"]] = Item(s["handle"], s["ref"], s["level"], s["tokens"], s["priority"], s["tree"],
                                          s["label"], s["reason"], ev.payload_object, s["text_hash"],
                                          last_used=ev.log_position)
            elif ev.kind == "context_reset":
                for item in items.values():
                    if item.state == "loaded":
                        item.state = "offloaded"
            elif s.get("handle") in items:
                item = items[s["handle"]]
                if ev.kind == "context_offload":
                    item.state, item.keep = "offloaded", s.get("keep") or item.keep
                elif ev.kind == "context_restore":
                    item.state, item.last_used = "loaded", ev.log_position
                elif ev.kind == "context_pin":
                    item.pinned = bool(s.get("pinned"))
            if s.get("handle") in items:
                items[s["handle"]].history.append({"event": ev.kind, "position": ev.log_position,
                                                   "reason": s.get("reason")})
        return items

    def used(self, session_id: str, ledger: dict | None = None) -> int:
        ledger = ledger if ledger is not None else self.ledger(session_id)
        return sum(i.tokens for i in ledger.values() if i.state == "loaded")

    def _record(self, kind: str, session_id: str, payload: bytes | None = None, **fields):
        return self.store.append(EventInput(kind=kind, session_id=session_id, writer_id=WRITER, agent="engine",
                                            summary_fields=fields, payload=payload))

    # ------------------------------------------------------------ rendering
    def _path(self, node_id: str) -> str:
        conn = self.store._connect()
        try:
            parts, current = [], node_id
            for _ in range(32):
                row = conn.execute("SELECT n.node_id, n.label, n.node_type FROM edges e JOIN nodes n ON n.node_id = e.from_id "
                                   "WHERE e.to_id = ? AND e.type = 'contains' LIMIT 1", (current,)).fetchone()
                if row is None or row[2] == "root":
                    break
                parts.append(row[1] or row[0])
                current = row[0]
            return "/".join(reversed(parts))
        finally:
            conn.close()

    def render(self, ref: dict, level: int = 1, max_bytes: int = 20000) -> tuple[str, str, str, str]:
        """(tree, label, text) for a reference at a level. Deterministic for unchanged records."""
        if "query" in ref:
            from agent_memory.tools import run_query
            text = run_query(self.store, ref["query"], ref.get("args") or {})
            tool = ref["query"].replace("mem_", "")
            return {"history": "history", "artifacts": "artifacts", "knowledge": "knowledge",
                    "state": "state"}.get(tool, "knowledge"), f"{ref['query']} {json.dumps(ref.get('args') or {}, sort_keys=True)}"[:120], text, "query"
        node_id = ref["node"]
        if node_id.startswith("state:") and node_id.split(":", 1)[1] in ("overview", "level1", "level2"):
            view = node_id.split(":", 1)[1]
            out = self.store.state.overview() if view == "overview" else self.store.state.level(int(view[-1]))
            return "state", f"state {view}", out["text"], "view"
        if node_id.startswith("state:") and node_id.split(":", 1)[1] in _sections():
            name = node_id.split(":", 1)[1]
            items = self.store.state.section(name)
            lines = [f"## {name.replace('_', ' ')}"] + [_state_line(i) for i in items]
            return "state", f"state section {name}", "\n".join(lines), "view"
        node = self.store.node(node_id)
        if node is None:
            raise ContextError(f"no record {node_id!r}")
        tree, a = node["tree"], node["attrs"]
        place = self._path(node["id"])
        label = f"{node['type']}: {node['label'] or node['id']}"
        meta = [m for m in (node["status"], node["basis"]) if m]
        links = {}
        for link in self.store.links(node["id"]):
            links[link["tree"]] = links.get(link["tree"], 0) + 1
        head = f"{label} ({'; '.join(meta)})" + (f" in {tree}/{place}" if place else f" in {tree}")
        if links:
            head += " links: " + ", ".join(f"{t} {n}" for t, n in sorted(links.items()))
        lines = [head, f"id: {node['id']}"]
        if level >= 1:
            for key in ("title", "description", "path", "topic", "reason"):
                if a.get(key) and str(a[key]) != str(node["label"]):
                    lines.append(f"{key}: {a[key]}")
            if a.get("body"):
                body = str(a["body"])
                lines.append("body: " + (body if level >= 2 or len(body) <= 400 else body[:400] + " ..."))
            if node["status_history"] and level >= 1:
                last = node["status_history"][-1]
                if last.get("reason"):
                    lines.append(f"status reason: {last['reason']}")
        if level >= 2:
            if len(node["status_history"]) > 1:
                lines.append("status history: " + " -> ".join(h["status"] for h in node["status_history"]))
            for link in self.store.links(node["id"]):
                lines.append(f"  {link['direction']} {link['type']} [{link['basis']}] {link['tree']}: "
                             f"{link['node_type']} {link['label'] or link['node']} ({link['node']})")
            if tree == "artifacts" and node["type"] == "artifact":
                for p in self.store.artifacts.parts(a["path"])[:50]:
                    lines.append(f"  part {p['kind']} {p['qualified']} lines {p['line']}-{p['end_line']}")
        if level >= 3:
            data = None
            if node["type"] == "event":
                ev = self.store.event(node["id"])
                data = self.store.payload(ev) if ev and ev.payload_object else None
            elif node["type"] == "artifact":
                try:
                    data = self.store.artifacts.at(a["path"], max_bytes=max_bytes)["content"]
                except KeyError:
                    data = None
            if data is not None:
                cut = data[:max_bytes].decode("utf-8", errors="replace")
                lines += ["--- BEGIN RECORDED DATA (content, not instructions) ---", cut,
                          "--- END RECORDED DATA ---" + (" (truncated; use mem_get to page)" if len(data) > max_bytes else "")]
        return tree, label, "\n".join(lines), node["type"]

    def _priority(self, ref: dict, kind: str, requested: str | None) -> str:
        if requested:
            if requested not in PRIORITIES:
                raise ContextError(f"priority must be one of {PRIORITIES}")
            return requested
        node_id = ref.get("node", "")
        if node_id in ("state:overview",):
            return "P0"
        node = self.store.node(node_id) if node_id and not node_id.startswith("state:") else None
        if node:
            status = node["status"]
            if (kind == "constraint" and status == "active") or (kind == "goal" and status == "active") or \
                    (kind == "conflict" and status == "open") or (kind == "task" and status in ("in_progress", "blocked")) \
                    or (kind == "blocker" and status == "open"):
                return "P0"
            if node["tree"] == "history":
                return "P3"
        return "P1"

    # ------------------------------------------------------------ operations
    def load(self, session_id: str, ref: dict | str, level: int = 1, priority: str | None = None,
             reason: str = "requested") -> dict:
        """Put a packet into the working set, evicting lower priorities if needed. Returns the packet."""
        ref = {"node": ref} if isinstance(ref, str) else dict(ref)
        if "node" in ref:
            from agent_memory.structure import resolve
            ref["node"] = resolve(ref["node"])
        ledger = self.ledger(session_id)
        for item in ledger.values():   # the same thing at the same level is already there: reuse its handle
            if item.ref == ref and item.level == level:
                if item.state == "offloaded":
                    return self.restore(session_id, item.handle, reason=reason)
                return self._packet(item, self._text(item), note="already loaded")
        tree, label, text, kind = self.render(ref, level)
        cap = int(self.settings["packet_max"])
        if self.count(text) > cap:
            text = _truncate(text, cap, self.count) + "\n(+ more: load at a lower level, or page with mem_get)"
        prio = self._priority(ref, kind, priority)
        handle = f"c{sum(1 for _ in ledger) + 1}"
        size = self.count(f"[{handle}] {text}") + 1   # as delivered: with its handle and a separator
        fits = self._make_room(session_id, ledger, size, tree, exclude=None)
        self._record("context_load", session_id, payload=text.encode(), handle=handle, ref=ref, level=level,
                     tokens=size, priority=prio, tree=tree, label=label[:200], reason=reason,
                     text_hash=hashlib.sha256(text.encode()).hexdigest())
        item = self.ledger(session_id)[handle]
        if not fits:
            self._record("context_offload", session_id, handle=handle, reason="doesn't fit the budget", auto=True)
            item.state = "offloaded"
            return self._packet(item, None, note=f"not loaded: {size} tokens doesn't fit the budget of "
                                                 f"{self.budget()} (P0 and pinned items use what's left)")
        return self._packet(item, text)

    def _make_room(self, session_id: str, ledger: dict, size: int, tree: str, exclude: str | None) -> bool:
        """Evict until `size` more tokens fit. False if it can't fit even after every allowed eviction."""
        budget = self.budget() - HEADER_RESERVE
        loaded = [i for i in ledger.values() if i.state == "loaded" and i.handle != exclude]
        used = sum(i.tokens for i in loaded)
        if used + size <= budget:
            return True
        protected = sum(i.tokens for i in loaded if i.priority == "P0" or i.pinned)
        if protected + size > budget:
            return False
        per_tree: dict[str, int] = {}
        for i in loaded:
            per_tree[i.tree] = per_tree.get(i.tree, 0) + i.tokens
        candidates = sorted((i for i in loaded if i.priority != "P0" and not i.pinned),
                            key=lambda i: (per_tree.get(i.tree, 0) <= self.share(i.tree),
                                           -PRIORITIES.index(i.priority), i.last_used, -i.tokens))
        for victim in candidates:
            if used + size <= budget:
                break
            self._record("context_offload", session_id, handle=victim.handle, auto=True,
                         reason=f"over budget: made room for {size} tokens")
            victim.state = "offloaded"
            used -= victim.tokens
            per_tree[victim.tree] -= victim.tokens
        return used + size <= budget

    def offload(self, session_id: str, handle: str, keep: str | None = None, force: bool = False,
                reason: str = "requested") -> dict:
        """Replace a loaded packet by its reference line. `keep` saves findings as a note linked to the record."""
        ledger = self.ledger(session_id)
        item = ledger.get(handle)
        if item is None:
            raise ContextError(f"no handle {handle!r} in session {session_id}")
        if (item.priority == "P0" or item.pinned) and not force:
            raise ContextError(f"{handle} is {'pinned' if item.pinned else 'P0'} and is protected; "
                               "offload it explicitly with force=True")
        if keep and "node" in item.ref and not item.ref["node"].startswith("state:"):
            self.store.append(EventInput(kind="note", session_id=session_id, writer_id=WRITER, agent="engine",
                                         summary_fields={"text": keep, "title": f"kept from {handle}: {keep[:60]}",
                                                         "note_type": "finding", "based_on": [item.ref["node"]]}))
        self._record("context_offload", session_id, handle=handle, keep=keep, auto=False,
                     reason=reason + (" (forced past protection)" if force and item.priority == "P0" else ""))
        item.state, item.keep = "offloaded", keep or item.keep
        return {"handle": handle, "state": "offloaded", "reference": item.reference(),
                "released_tokens": item.tokens}

    def restore(self, session_id: str, handle: str, reason: str = "requested") -> dict:
        """Bring an offloaded packet back: exactly the text that was loaded, plus a note if the record changed."""
        ledger = self.ledger(session_id)
        item = ledger.get(handle)
        if item is None:
            raise ContextError(f"no handle {handle!r} in session {session_id}")
        if item.state == "loaded":
            return self._packet(item, self._text(item), note="already loaded")
        if not self._make_room(session_id, ledger, item.tokens, item.tree, exclude=handle):
            return self._packet(item, None, note="not restored: it doesn't fit the budget")
        self._record("context_restore", session_id, handle=handle, reason=reason)
        item.state = "loaded"
        text = self._text(item)
        note = None
        try:
            current = self.render(item.ref, item.level)[2]
            if hashlib.sha256(current.encode()).hexdigest() != item.text_hash and "query" not in item.ref:
                note = "the record has changed since this was loaded; load it again for the current version"
        except ContextError:
            note = "the record no longer exists"
        return self._packet(item, text, note=note)

    def pin(self, session_id: str, handle: str, pinned: bool = True) -> dict:
        if handle not in self.ledger(session_id):
            raise ContextError(f"no handle {handle!r} in session {session_id}")
        self._record("context_pin", session_id, handle=handle, pinned=pinned)
        return {"handle": handle, "pinned": pinned}

    def _text(self, item: Item) -> str:
        return self.store.archive.get(item.object_id).decode() if item.object_id else ""

    def _packet(self, item: Item, text: str | None, note: str | None = None) -> dict:
        p = {"handle": item.handle, "tree": item.tree, "ref": item.ref, "level": item.level, "tokens": item.tokens,
             "priority": item.priority, "pinned": item.pinned, "label": item.label,
             "state": "loaded" if text is not None else "offloaded",
             "text": text if text is not None else item.reference()}
        if note:
            p["note"] = note
        return p

    # ------------------------------------------------------------ relevance and missing context
    def detect(self, session_id: str, prompt: str, limit: int = 8) -> list[dict]:
        """Records the prompt names (or matches) that the working set lacks, best first, with reasons."""
        ledger = self.ledger(session_id)
        loaded = {json.dumps(i.ref, sort_keys=True) for i in ledger.values() if i.state == "loaded"}
        by_ref = {i.ref.get("node"): i for i in ledger.values()}
        found: dict[str, dict] = {}

        def offer(node_id: str, score: float, why: str) -> None:
            if json.dumps({"node": node_id}, sort_keys=True) in loaded:
                return
            o = found.setdefault(node_id, {"node": node_id, "score": 0.0, "reasons": []})
            o["score"] += score
            if why not in o["reasons"]:
                o["reasons"].append(why)

        for match in ID_PATTERN.findall(prompt):
            if self.store.node(match):
                offer(match, 1.0, f"named: {match}")
        current = self.store.current_files()
        self.store.update_artifacts()   # once per prompt; lookups below read the index directly
        for raw in PATH_PATTERN.findall(prompt):
            for path in current:
                if path == raw or path.endswith("/" + raw):
                    offer(f"artifact:{path}", 1.0, f"mentions the file {raw}")
        for word in {w for w in WORD_PATTERN.findall(prompt) if len(w) >= 3 and w.lower() not in STOPWORDS}:
            for part in self.store.codegraph.find_part(word)[:3]:
                offer(f"artifact:{part['path']}", 0.8, f"mentions {part['kind']} {part['qualified']}")
        conn = self.store._connect()
        try:
            topics = conn.execute("SELECT node_id, label FROM nodes WHERE node_type = 'topic'").fetchall()
        finally:
            conn.close()
        lower = prompt.lower()
        for node_id, label in topics:
            if label and label.lower() != "unfiled" and re.search(rf"\b{re.escape(label.lower())}\b", lower):
                offer(node_id, 0.6, f"mentions the topic {label}")
        terms = [w for w in WORD_PATTERN.findall(prompt) if len(w) >= 3 and w.lower() not in STOPWORDS]
        for node_id, _snippet, _rank in self.store.search_index.knowledge_any(terms, limit=limit):
            offer(node_id, 0.5, "matches the prompt in knowledge")
        # One link away from something the prompt names: knowledge and state about it (link distance).
        for node_id, o in list(found.items()):
            if o["score"] < 0.8:
                continue
            for link in self.store.links(node_id):
                if link["tree"] in ("knowledge", "state"):
                    offer(link["node"], 0.3, f"{link['type']} {node_id}")
        out = []
        for node_id, o in sorted(found.items(), key=lambda kv: (-kv[1]["score"], kv[0])):
            node = self.store.node(node_id)
            if node is None:
                continue
            if node["status"] in ("open", "in_progress", "active", "blocked"):
                o["score"] += 0.2
            previous = by_ref.get(node_id)
            label = f"{node['type']}: {node['label'] or node_id}"
            line = (f"[{previous.handle}] {label} ({node['tree']}) - offloaded; mem_restore {previous.handle}"
                    if previous else f"{label} ({node['tree']}, {node_id}) - mem_load {node_id}")
            out.append({**o, "tree": node["tree"], "label": label, "line": line + " - " + "; ".join(o["reasons"]),
                        "handle": previous.handle if previous else None})
        out.sort(key=lambda o: (-o["score"], o["node"]))
        return out[:limit]

    # ------------------------------------------------------------ assembling and recovering
    def _p0_records(self) -> list[str]:
        conn = self.store._connect()
        try:
            rows = conn.execute("SELECT node_id, node_type FROM nodes WHERE node_type IN "
                                "('constraint', 'goal', 'conflict', 'task', 'blocker') ORDER BY log_position").fetchall()
        finally:
            conn.close()
        wanted = {"constraint": ("active",), "goal": ("active",), "conflict": ("open",),
                  "task": ("in_progress", "blocked"), "blocker": ("open",)}
        out = []
        for node_id, kind in rows:
            node = self.store.node(node_id)
            if node and node["status"] in wanted[kind]:
                out.append(node_id)
        return out

    def assemble(self, session_id: str, prompt: str | None = None, previous_session: str | None = None,
                 budget: int | None = None) -> dict:
        """Session start: overview, every P0 record, level-1 state, the last working set as references, offers.

        `budget` caps this delivery (for example an agent's limit on injected context). Later loads use the full
        budget again.
        """
        self._override = budget
        try:
            return self._assemble(session_id, prompt, previous_session)
        finally:
            self._override = None

    def _assemble(self, session_id: str, prompt: str | None, previous_session: str | None) -> dict:
        self.load(session_id, "state:overview", 0, "P0", reason="assemble")
        for node_id in self._p0_records():
            self.load(session_id, node_id, 1, "P0", reason="assemble: protected")
        self.load(session_id, "state:level1", 1, "P1", reason="assemble")
        previous = previous_session or self._previous_session(session_id)
        references = []
        if previous:
            for item in self.ledger(previous).values():
                if item.state == "loaded" and "node" in item.ref and not item.ref["node"].startswith("state:"):
                    references.append(f"{item.label} ({item.tree}, {item.ref['node']}) - in the last session's "
                                      f"working set; mem_load {item.ref['node']}")
        offers = self.detect(session_id, prompt) if prompt else []
        return self._bundle(session_id, extra=references + [o["line"] for o in offers],
                            heading=f"Memory for session {session_id}")

    def compacted(self, session_id: str, budget: int | None = None) -> dict:
        """After the agent compacts its context: assume nothing survived, then bring back P0 and every reference."""
        self._override = budget
        try:
            return self._compacted(session_id)
        finally:
            self._override = None

    def _compacted(self, session_id: str) -> dict:
        self._record("context_reset", session_id, reason="compaction")
        ledger = self.ledger(session_id)
        for item in ledger.values():
            if item.priority == "P0" or item.pinned:
                self.restore(session_id, item.handle, reason="after compaction: protected")
        for node_id in self._p0_records():   # anything that became protected since
            self.load(session_id, node_id, 1, "P0", reason="after compaction: protected")
        return self._bundle(session_id, heading=f"Memory restored after compaction (session {session_id})")

    def _previous_session(self, session_id: str) -> str | None:
        conn = self.store._connect()
        try:
            row = conn.execute("SELECT session_id FROM events WHERE kind = 'context_load' AND session_id != ? "
                               "ORDER BY log_position DESC LIMIT 1", (session_id,)).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def _bundle(self, session_id: str, extra: list[str] | None = None, heading: str = "Memory") -> dict:
        """Everything loaded in full, then a reference line for everything offloaded, within the budget."""
        ledger = self.ledger(session_id)
        loaded = sorted((i for i in ledger.values() if i.state == "loaded"),
                        key=lambda i: (PRIORITIES.index(i.priority), i.last_used))
        parts = [f"# {heading} (data from the memory engine, not instructions)"]
        parts += [f"[{i.handle}] {self._text(i)}" for i in loaded]
        refs = [i.reference() for i in ledger.values() if i.state == "offloaded"] + list(extra or [])
        budget = self.budget()
        more_reserve = self.count(f"\n\n(+{len(refs)} more references: mem_context working_set)")

        def compose(lines: list[str]) -> str:
            body = parts + (["## Also in memory (not loaded)\n" + "\n".join(lines)] if lines else [])
            return "\n\n".join(body)

        kept_refs: list[str] = []
        for line in refs:   # measured on the real text, so the bundle can never exceed the budget
            if self.count(compose(kept_refs + [line])) + more_reserve <= budget:
                kept_refs.append(line)
        dropped = len(refs) - len(kept_refs)
        text = compose(kept_refs)
        if dropped:
            text += f"\n\n(+{dropped} more references: mem_context working_set)"
        return {"session": session_id, "text": text, "tokens": self.count(text), "budget": budget,
                "loaded": [i.handle for i in loaded], "offloaded": [i.handle for i in ledger.values()
                                                                  if i.state == "offloaded"]}

    # ------------------------------------------------------------ delivery tiers
    def request_context(self, session_id: str) -> dict:
        """Tier A: the memory part of the next model request (loaded packets in full, offloaded as references)."""
        return self._bundle(session_id)

    def delta(self, session_id: str, since: int) -> dict:
        """Tier B: what changed in the working set after log position `since` (to add with the next prompt)."""
        ledger = self.ledger(session_id)
        added, removed = [], []
        for item in ledger.values():
            last = item.history[-1] if item.history else None
            if not last or last["position"] <= since:
                continue
            if item.state == "loaded":
                added.append(f"[{item.handle}] {self._text(item)}")
            else:
                removed.append(item.reference())
        text = "\n\n".join(added + (["## Offloaded\n" + "\n".join(removed)] if removed else []))
        position = max((h["position"] for i in ledger.values() for h in i.history), default=since)
        return {"session": session_id, "text": text, "tokens": self.count(text), "position": position}

    def working_set(self, session_id: str) -> dict:
        ledger = self.ledger(session_id)
        rows = [{"handle": i.handle, "label": i.label, "tree": i.tree, "level": i.level, "tokens": i.tokens,
                 "priority": i.priority, "pinned": i.pinned, "state": i.state, "keep": i.keep} for i in ledger.values()]
        per_tree = {t: sum(i.tokens for i in ledger.values() if i.state == "loaded" and i.tree == t) for t in TREES}
        return {"session": session_id, "budget": self.budget(), "used": self.used(session_id, ledger),
                "per_tree": per_tree, "shares": {t: self.share(t) for t in TREES}, "items": rows}


def _sections() -> tuple:
    from agent_memory.state import SECTIONS
    return SECTIONS


def _state_line(item: dict) -> str:
    meta = ", ".join(x for x in (item.get("status"), item.get("source")) if x)
    line = f"- [{item['id']}] {item['label']} ({meta})"
    return line + (f" STALE: {item['stale_reasons'][0]}" if item.get("stale") else "")


def _truncate(text: str, cap: int, count) -> str:
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count(text[:mid]) <= cap - 20:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]
