"""The permanent core's write path: the event log and the raw archive (design sections 4, 5 and 11).

`Store.append()` turns an adapter's EventInput into a stored, canonical event:

1. **Idempotency.** A retried hook with the same `idempotency_key` gets the
   event it already stored, not a second one.
2. **Exclusions.** File content whose path matches an exclusion pattern
   isn't stored. An `exclusion` event records the path and a keyed
   fingerprint of the content instead.
3. **Redaction.** The payload and every string in the summary fields are
   scanned for secrets, and each one is replaced by a marker. The event
   carries redaction records (rule, location, fingerprint), never values.
4. **Archive.** The full payload goes into the raw archive. If it can't be
   stored whole, a `capture_gap` event names what was missed, and nothing
   partial is kept.
5. **Log.** The event is appended in one transaction, with a per-writer
   sequence number and a hash chained to that writer's previous record.
   SQLite triggers refuse any UPDATE or DELETE on the log.

`Store.verify()` checks the chains and every archived object, and reports
problems; it never repairs anything.
"""
from __future__ import annotations

import fnmatch
import json
import os
import secrets as _secrets
import sqlite3
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from agent_memory import keys, navigate, structure
from agent_memory.archive import Archive, ArchiveError, CorruptObject
from agent_memory.location import synced_folder_warnings
from agent_memory.schema import SCHEMA_VERSION, Event, EventInput, canonical_json
from agent_memory.secrets import SecretScanner

STORE_FORMAT = 1
DEFAULT_EXCLUSIONS = (".env", ".env.*", "*.pem", "*.key", "id_rsa", "id_ed25519", "*.p12", "*.pfx",
                      ".netrc", ".npmrc", ".pypirc", "credentials.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _sha256(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


class Store:
    def __init__(self, path: str | os.PathLike, project_id: str | None = None,
                 exclusions: tuple[str, ...] = DEFAULT_EXCLUSIONS, quota_bytes: int | None = None,
                 min_free_bytes: int | None = None, key_dir: Path | None = None):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.warnings = synced_folder_warnings(self.path)
        for w in self.warnings:
            warnings.warn(w, stacklevel=2)
        self.project_id = project_id or self.path.name
        self.exclusions = tuple(exclusions)
        self._db = self.path / "memory.db"
        self._init_db()
        data_key, id_key, fp_key = self._unlock(key_dir)
        kwargs = {} if min_free_bytes is None else {"min_free_bytes": min_free_bytes}
        self.archive = Archive(self.path, data_key, id_key, quota_bytes=quota_bytes, **kwargs)
        self.scanner = SecretScanner(fp_key)

    # ------------------------------------------------------------ setup
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db, isolation_level=None, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    log_position INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    schema_version INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    parent_id TEXT,
                    writer_id TEXT NOT NULL,
                    writer_seq INTEGER NOT NULL,
                    agent TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    adapter_version TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    payload_object TEXT,
                    summary_fields TEXT NOT NULL,
                    completeness TEXT NOT NULL,
                    redactions TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE,
                    prev_hash TEXT NOT NULL,
                    record_hash TEXT NOT NULL,
                    UNIQUE (writer_id, writer_seq)
                );
                CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
                CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
                CREATE TRIGGER IF NOT EXISTS events_append_only_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'the event log is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS events_append_only_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'the event log is append-only'); END;
            """)
            structure.create(conn)
            conn.execute("INSERT OR IGNORE INTO meta VALUES ('store_format', ?)", (str(STORE_FORMAT),))
            conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            conn.execute("INSERT OR IGNORE INTO meta VALUES ('created_at', ?)", (_now(),))
        finally:
            conn.close()

    def _meta(self, conn, key: str):
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _unlock(self, key_dir: Path | None) -> tuple[bytes, bytes, bytes]:
        conn = self._connect()
        try:
            passphrase = os.environ.get("AMEM_PASSPHRASE")
            conn.execute("BEGIN IMMEDIATE")
            source = self._meta(conn, "kek_source")
            if source is None:
                source = "passphrase" if passphrase else "key_file"
                conn.execute("INSERT INTO meta VALUES ('kek_source', ?)", (source,))
                if source == "passphrase":
                    conn.execute("INSERT INTO meta VALUES ('kek_salt', ?)", (_secrets.token_bytes(16),))
            if source == "passphrase":
                if not passphrase:
                    raise keys.KeyError_("this store is locked with a passphrase: set AMEM_PASSPHRASE")
                kek = keys.passphrase_kek(passphrase, self._meta(conn, "kek_salt"))
            else:
                kek = keys.key_file_kek(self.project_id, key_dir)
            unlocked = []
            for label in ("data_key", "object_id_key", "fingerprint_key"):
                blob = self._meta(conn, label)
                if blob is None:
                    key = _secrets.token_bytes(keys.KEY_BYTES)
                    conn.execute("INSERT INTO meta VALUES (?, ?)", (label, keys.wrap(kek, key, label)))
                else:
                    key = keys.unwrap(kek, blob, label)
                unlocked.append(key)
            conn.execute("COMMIT")
            return tuple(unlocked)
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------ writing
    def _excluded(self, path: str | None) -> bool:
        if not path:
            return False
        name = os.path.basename(path)
        return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(name, p) for p in self.exclusions)

    def _redact_value(self, value: Any, field: str, redactions: list) -> Any:
        if isinstance(value, str):
            clean, found = self.scanner.redact(value.encode(), field)
            redactions.extend(r.record() for r in found)
            return clean.decode(errors="replace") if found else value
        if isinstance(value, dict):
            return {k: self._redact_value(v, f"{field}.{k}", redactions) for k, v in value.items()}
        if isinstance(value, list):
            return [self._redact_value(v, f"{field}[{i}]", redactions) for i, v in enumerate(value)]
        return value

    def append(self, inp: EventInput) -> Event:
        inp.validate()
        if inp.idempotency_key:
            existing = self._by_idempotency(inp.idempotency_key)
            if existing:
                return existing
        payload = inp.payload.encode() if isinstance(inp.payload, str) else inp.payload
        kind, completeness = inp.kind, inp.completeness
        summary = dict(inp.summary_fields)
        redactions: list[dict] = []
        summary = self._redact_value(summary, "summary", redactions)
        payload_object = None

        if payload is not None and self._excluded(inp.path):
            summary = {"path": inp.path, "excluded_kind": inp.kind, "size": len(payload),
                       "content_fingerprint": self.scanner.fingerprint(payload), "reason": "excluded path"}
            kind, completeness, payload = "exclusion", "unavailable", None
        elif payload is not None:
            clean, found = self.scanner.redact(payload, "payload")
            redactions.extend(r.record() for r in found)
            try:
                payload_object = self.archive.put(clean)
            except ArchiveError as err:
                summary = {"missed_kind": inp.kind, "missed_summary": summary, "size": len(payload),
                           "content_fingerprint": self.scanner.fingerprint(payload), "reason": str(err)}
                kind, completeness = "capture_gap", "unavailable"
                redactions = [r for r in redactions if r["field"] != "payload"]

        recorded = _now()
        return self._insert({
            "event_id": uuid.uuid4().hex, "schema_version": SCHEMA_VERSION, "kind": kind,
            "session_id": inp.session_id, "parent_id": inp.parent_id, "writer_id": inp.writer_id,
            "agent": inp.agent, "agent_version": inp.agent_version, "adapter_version": inp.adapter_version,
            "occurred_at": inp.occurred_at or recorded, "recorded_at": recorded,
            "payload_object": payload_object, "summary_fields": summary, "completeness": completeness,
            "redactions": redactions, "idempotency_key": inp.idempotency_key,
        })

    def _insert(self, record: dict) -> Event:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if record["idempotency_key"]:
                row = conn.execute("SELECT * FROM events WHERE idempotency_key = ?",
                                   (record["idempotency_key"],)).fetchone()
                if row:   # a concurrent retry won the race
                    conn.execute("COMMIT")
                    return self._row(row)
            structure.validate(conn, record["kind"], record["summary_fields"])
            last = conn.execute("SELECT writer_seq, record_hash FROM events WHERE writer_id = ? "
                                "ORDER BY writer_seq DESC LIMIT 1", (record["writer_id"],)).fetchone()
            record["writer_seq"] = (last[0] + 1) if last else 1
            record["prev_hash"] = last[1] if last else f"genesis:{record['writer_id']}"
            draft = Event(log_position=0, record_hash="", **record)
            record_hash = _sha256(canonical_json(draft.hashed_fields()))
            cur = conn.execute(
                """INSERT INTO events (event_id, schema_version, kind, session_id, parent_id, writer_id, writer_seq,
                       agent, agent_version, adapter_version, occurred_at, recorded_at, payload_object,
                       summary_fields, completeness, redactions, idempotency_key, prev_hash, record_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record["event_id"], record["schema_version"], record["kind"], record["session_id"],
                 record["parent_id"], record["writer_id"], record["writer_seq"], record["agent"],
                 record["agent_version"], record["adapter_version"], record["occurred_at"],
                 record["recorded_at"], record["payload_object"], canonical_json(record["summary_fields"]),
                 record["completeness"], canonical_json(record["redactions"]), record["idempotency_key"],
                 record["prev_hash"], record_hash))
            stored = Event(log_position=cur.lastrowid, record_hash=record_hash, **record)
            structure.apply(conn, stored)   # the tree and graph change in the same transaction
            conn.execute("COMMIT")
            return stored
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------ reading
    @staticmethod
    def _row(row) -> Event:
        (pos, event_id, schema_version, kind, session_id, parent_id, writer_id, writer_seq, agent,
         agent_version, adapter_version, occurred_at, recorded_at, payload_object, summary, completeness,
         redactions, idempotency_key, prev_hash, record_hash) = row
        return Event(pos, event_id, schema_version, kind, session_id, parent_id, writer_id, writer_seq, agent,
                     agent_version, adapter_version, occurred_at, recorded_at, payload_object,
                     json.loads(summary), completeness, json.loads(redactions), idempotency_key,
                     prev_hash, record_hash)

    def _by_idempotency(self, key: str) -> Event | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM events WHERE idempotency_key = ?", (key,)).fetchone()
            return self._row(row) if row else None
        finally:
            conn.close()

    def events(self, session_id: str | None = None, kind: str | None = None) -> Iterator[Event]:
        conn = self._connect()
        try:
            sql, args = "SELECT * FROM events", []
            where = []
            if session_id:
                where.append("session_id = ?"); args.append(session_id)
            if kind:
                where.append("kind = ?"); args.append(kind)
            if where:
                sql += " WHERE " + " AND ".join(where)
            for row in conn.execute(sql + " ORDER BY log_position", args).fetchall():
                yield self._row(row)
        finally:
            conn.close()

    def event(self, event_id: str) -> Event | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
            return self._row(row) if row else None
        finally:
            conn.close()

    def payload(self, event: Event | str) -> bytes | None:
        """The full archived payload, byte for byte (after redaction), or None if the event has none."""
        ev = self.event(event) if isinstance(event, str) else event
        if ev is None or ev.payload_object is None:
            return None
        return self.archive.get(ev.payload_object)

    def count(self) -> int:
        conn = self._connect()
        try:
            return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            conn.close()

    # ------------------------------------------------------------ integrity
    def verify(self) -> dict:
        """Check every writer's hash chain and every archived object. Reports; never repairs."""
        problems: list[dict] = []
        chains: dict[str, tuple[int, str]] = {}
        referenced: set[str] = set()
        positions = []
        for ev in self.events():
            positions.append(ev.log_position)
            last_seq, last_hash = chains.get(ev.writer_id, (0, f"genesis:{ev.writer_id}"))
            if ev.writer_seq != last_seq + 1:
                problems.append({"type": "sequence_gap", "event_id": ev.event_id, "writer_id": ev.writer_id,
                                 "expected_seq": last_seq + 1, "found_seq": ev.writer_seq})
            if ev.prev_hash != last_hash:
                problems.append({"type": "chain_break", "event_id": ev.event_id, "writer_id": ev.writer_id})
            if _sha256(canonical_json(ev.hashed_fields())) != ev.record_hash:
                problems.append({"type": "record_altered", "event_id": ev.event_id,
                                 "log_position": ev.log_position})
            chains[ev.writer_id] = (ev.writer_seq, ev.record_hash)
            if ev.payload_object:
                referenced.add(ev.payload_object)
        for oid in sorted(referenced):
            try:
                self.archive.get(oid)
            except CorruptObject as err:
                problems.append({"type": "object_problem", "object_id": oid, "detail": str(err)})
        conn = self._connect()
        try:
            stored = structure.snapshot(conn)
        finally:
            conn.close()
        rebuilt = structure.rebuild(self.events())
        for table in structure.TABLES:
            if stored[table] != rebuilt[table]:
                problems.append({"type": "structure_mismatch", "table": table,
                                 "detail": "doesn't match a rebuild from the event log"})
        return {"ok": not problems, "events": len(positions), "writers": len(chains),
                "objects_checked": len(referenced), "problems": problems}

    # ------------------------------------------------------------ declaring structure (design 6.2-6.4)
    def declare(self, kind: str, session_id: str, writer_id: str, **fields) -> Event:
        """Append a declared event (path, goal, task, blocker, decision, note, relation, retraction)."""
        return self.append(EventInput(kind=kind, session_id=session_id, writer_id=writer_id,
                                      summary_fields=fields, agent=fields.pop("agent", "unknown")))

    def create(self, kind: str, session_id: str, writer_id: str, **fields) -> str:
        """Create a planning record and return its id (for example "path:<event id>")."""
        return f"{kind}:{self.declare(kind, session_id, writer_id, op='create', **fields).event_id}"

    def set_status(self, kind: str, record_id: str, status: str, session_id: str, writer_id: str, **fields) -> Event:
        return self.declare(kind, session_id, writer_id, op="status", id=record_id, status=status, **fields)

    def relate(self, src: str, dst: str, type: str, session_id: str, writer_id: str,
               basis: str = "declared", reason: str | None = None) -> Event:
        return self.declare("relation", session_id, writer_id, **{"from": src, "to": dst, "type": type,
                                                                  "basis": basis, "reason": reason})

    def retract(self, edge_id: int, session_id: str, writer_id: str, reason: str | None = None) -> Event:
        return self.declare("retraction", session_id, writer_id, edge_id=edge_id, reason=reason)

    # ------------------------------------------------------------ navigation (design 6.1)
    def _nav(self, fn, *args, **kwargs):
        conn = self._connect()
        try:
            return fn(conn, *args, **kwargs)
        finally:
            conn.close()

    def node(self, node_id: str, include_retracted: bool = False):
        return self._nav(navigate.node, node_id, include_retracted)

    def tree(self, node_id: str = "project", depth: int = 2):
        return self._nav(navigate.tree, node_id, depth)

    def trace(self, start: str, types=None, direction: str = "out", depth: int = 6):
        return self._nav(navigate.trace, start, types, direction, depth)

    def edges(self, node_id: str, direction: str = "out", types=None, include_retracted: bool = False):
        return self._nav(navigate.edges, node_id, direction, types, include_retracted)

    def project_view(self):
        return self._nav(navigate.project)

    def session_view(self, session_id: str):
        return self._nav(navigate.session, session_id)

    def event_view(self, event_id: str):
        return self._nav(navigate.event, event_id)

    def file_view(self, path: str):
        return self._nav(navigate.file, path)

    def decision_view(self, decision_id: str):
        return self._nav(navigate.decision, decision_id)

    def path_view(self, path_id: str):
        return self._nav(navigate.path, path_id)

    def verification_view(self, event_id: str):
        ev = self.event(event_id)
        return self._nav(navigate.verification, event_id, ev.summary_fields if ev else {})
