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

from agent_memory import keys
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
            conn.execute("COMMIT")
            return Event(log_position=cur.lastrowid, record_hash=record_hash, **record)
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
        return {"ok": not problems, "events": len(positions), "writers": len(chains),
                "objects_checked": len(referenced), "problems": problems}
