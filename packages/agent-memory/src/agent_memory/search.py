"""Full-text search over the knowledge and history trees (architecture revision 3, sections 4.1 and 4.3).

A derived index, like the artifact index:
- **incremental:** it indexes what was added since the last update, by log position;
- **rebuildable:** `rebuild()` recreates it from the core and the archive;
- **not part of the core's integrity check.**

What it indexes:
- **Knowledge:** every knowledge-tree node's title and body (entries, topics
  and their descriptions). Entries are never rewritten, because a status
  change is a new row, so indexing each node once is complete.
- **History:** the text of conversation events (`user_message`,
  `assistant_message`, `compaction`): the `text` field plus the archived
  payload when it is text. The archive holds redacted content only, so a
  secret can't be found by searching.

Queries are quoted term by term, so user input is never FTS syntax.
"""
from __future__ import annotations

import json

HISTORY_KINDS = ("user_message", "assistant_message", "compaction")
MAX_BODY = 1_000_000

SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(node_id UNINDEXED, node_type UNINDEXED, title, body);
CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5(event_id UNINDEXED, session_id UNINDEXED, kind UNINDEXED,
                                                          body);
CREATE TABLE IF NOT EXISTS search_state (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""


def _quote(query: str) -> str:
    return " ".join('"' + t.replace('"', '""') + '"' for t in query.split())


class SearchIndex:
    def __init__(self, conn_factory, archive):
        self._connect = conn_factory
        self._archive = archive
        conn = self._connect()
        try:
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    def _state(self, conn, key: str) -> int:
        row = conn.execute("SELECT value FROM search_state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else 0

    def update(self) -> dict:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            k_from, h_from = self._state(conn, "knowledge"), self._state(conn, "history")
            added = {"knowledge": 0, "history": 0}
            k_last = k_from
            for node_id, node_type, label, attrs, pos in conn.execute(
                    "SELECT node_id, node_type, label, attrs, log_position FROM nodes "
                    "WHERE tree = 'knowledge' AND node_type != 'root' AND log_position > ? ORDER BY log_position",
                    (k_from,)).fetchall():
                a = json.loads(attrs)
                body = " ".join(str(a[k]) for k in ("description", "body") if a.get(k))
                conn.execute("INSERT INTO knowledge_fts VALUES (?, ?, ?, ?)", (node_id, node_type, label or "", body))
                added["knowledge"] += 1
                k_last = max(k_last, pos)
            h_last = h_from
            for event_id, session_id, kind, summary, payload, pos in conn.execute(
                    f"SELECT event_id, session_id, kind, summary_fields, payload_object, log_position FROM events "
                    f"WHERE log_position > ? AND kind IN ({','.join('?' * len(HISTORY_KINDS))}) "
                    f"ORDER BY log_position", (h_from, *HISTORY_KINDS)).fetchall():
                parts = [str(json.loads(summary).get("text") or "")]
                if payload:
                    try:
                        data = self._archive.get(payload)[:MAX_BODY]
                        if b"\0" not in data[:8192]:
                            parts.append(data.decode("utf-8", errors="replace"))
                    except Exception:   # a missing object is verify's to report; search just skips it
                        pass
                conn.execute("INSERT INTO history_fts VALUES (?, ?, ?, ?)",
                             (event_id, session_id, kind, "\n".join(p for p in parts if p)))
                added["history"] += 1
                h_last = max(h_last, pos)
            last = conn.execute("SELECT COALESCE(MAX(log_position), 0) FROM events").fetchone()[0]
            conn.execute("INSERT OR REPLACE INTO search_state VALUES ('knowledge', ?)", (max(k_last, k_from),))
            conn.execute("INSERT OR REPLACE INTO search_state VALUES ('history', ?)", (max(h_last, last),))
            conn.execute("COMMIT")
            return added
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def rebuild(self) -> dict:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM knowledge_fts")
            conn.execute("DELETE FROM history_fts")
            conn.execute("DELETE FROM search_state")
            conn.commit()
        finally:
            conn.close()
        return self.update()

    def knowledge(self, query: str, limit: int = 50) -> list[tuple[str, str, float]]:
        """(node id, snippet, rank) for knowledge nodes matching every term."""
        terms = _quote(query)
        if not terms:
            return []
        self.update()
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT node_id, snippet(knowledge_fts, -1, '[', ']', ' ... ', 12), rank FROM knowledge_fts "
                "WHERE knowledge_fts MATCH ? ORDER BY rank LIMIT ?", (terms, limit)).fetchall()
        finally:
            conn.close()

    def history(self, query: str, limit: int = 20, session_id: str | None = None) -> list[dict]:
        terms = _quote(query)
        if not terms:
            return []
        self.update()
        conn = self._connect()
        try:
            sql = ("SELECT event_id, session_id, kind, snippet(history_fts, 3, '[', ']', ' ... ', 12), rank "
                   "FROM history_fts WHERE history_fts MATCH ?")
            args: list = [terms]
            if session_id:
                sql += " AND session_id = ?"
                args.append(session_id)
            return [{"event_id": e, "session_id": s, "kind": k, "snippet": snip, "rank": r}
                    for e, s, k, snip, r in conn.execute(sql + " ORDER BY rank LIMIT ?", (*args, limit))]
        finally:
            conn.close()
