"""Checkpoints, recovery and rebuilding (design sections 8.2 and 8.3).

The event log is the truth; everything else can be rebuilt from it.

* **A checkpoint** records:
  - a log position;
  - every writer's chain head at that position;
  - a snapshot of the core structure tables, stored encrypted in the archive.

  It is written in its own transaction, after the events it covers are
  committed. Checkpoints are taken at session end, every CHECKPOINT_EVERY
  events, and before large reconciliations.
* **Recovery:**
  1. Load the newest checkpoint that passes every check: its snapshot
     decrypts, matches its hash, and its chain heads match the log.
  2. Replay the events after it.
  3. Compare the result with the stored structure, and repair only the
     tables that differ, never the log.
  4. Rebuild the derived layer.
  5. Optionally reconcile.
  6. Record the recovery itself as an event.

  Problems found on the way are reported, never silently fixed in the log.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from agent_memory import structure
from agent_memory.archive import CorruptObject

CHECKPOINT_EVERY = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT, log_position INTEGER NOT NULL, chain_heads TEXT NOT NULL,
    snapshot_object TEXT NOT NULL, snapshot_hash TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL);
"""


def create(conn) -> None:
    conn.executescript(SCHEMA)
    for action in ("UPDATE", "DELETE"):
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS checkpoints_append_only_{action.lower()} BEFORE {action} "
                     f"ON checkpoints BEGIN SELECT RAISE(ABORT, 'the checkpoints table is append-only'); END")


def _heads(conn, upto: int) -> dict[str, list]:
    rows = conn.execute("""SELECT writer_id, writer_seq, record_hash FROM events e WHERE log_position <= ? AND
                           writer_seq = (SELECT MAX(writer_seq) FROM events WHERE writer_id = e.writer_id
                                         AND log_position <= ?)""", (upto, upto))
    return {w: [seq, h] for w, seq, h in rows}


def _encode(snap: dict) -> bytes:
    from agent_memory.store import STORE_FORMAT
    return json.dumps({"format": STORE_FORMAT, "tables": {t: [list(r) for r in rows] for t, rows in snap.items()}},
                      separators=(",", ":")).encode()


def checkpoint(store, reason: str = "manual") -> int | None:
    """Snapshot the core structure at the current log position. Returns the checkpoint id."""
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        position = conn.execute("SELECT COALESCE(MAX(log_position), 0) FROM events").fetchone()[0]
        if position == 0:
            conn.execute("ROLLBACK")
            return None
        last = conn.execute("SELECT log_position FROM checkpoints ORDER BY checkpoint_id DESC LIMIT 1").fetchone()
        if last and last[0] == position:
            conn.execute("ROLLBACK")
            return None
        snapshot = _encode(structure.snapshot(conn))
        heads = _heads(conn, position)
        conn.execute("COMMIT")
    finally:
        conn.close()
    object_id = store.archive.put(snapshot)   # outside the transaction; content-addressed and atomic
    conn = store._connect()
    try:
        cur = conn.execute("INSERT INTO checkpoints (log_position, chain_heads, snapshot_object, snapshot_hash, "
                           "reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                           (position, json.dumps(heads, sort_keys=True), object_id,
                            hashlib.sha256(snapshot).hexdigest(), reason, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def check_checkpoint(store, conn, row) -> tuple[bool, str, dict | None]:
    """(valid, reason, snapshot) for one checkpoint row."""
    checkpoint_id, position, heads, object_id, snapshot_hash, _reason, _at = row
    try:
        raw = store.archive.get(object_id)
    except CorruptObject as err:
        return False, f"checkpoint {checkpoint_id}: {err}", None
    if hashlib.sha256(raw).hexdigest() != snapshot_hash:
        return False, f"checkpoint {checkpoint_id}: snapshot doesn't match its hash", None
    if _heads(conn, position) != json.loads(heads):
        return False, f"checkpoint {checkpoint_id}: chain heads don't match the log at position {position}", None
    from agent_memory.store import STORE_FORMAT
    data = json.loads(raw)
    if data.get("format") != STORE_FORMAT:
        return False, f"checkpoint {checkpoint_id}: written by an older store format (superseded)", None
    return True, "", {t: [tuple(r) for r in rows] for t, rows in data["tables"].items()}


def checkpoints_report(store) -> list[dict]:
    conn = store._connect()
    try:
        out = []
        for row in conn.execute("SELECT * FROM checkpoints ORDER BY checkpoint_id").fetchall():
            ok, reason, _ = check_checkpoint(store, conn, row)
            out.append({"checkpoint_id": row[0], "log_position": row[1], "valid": ok, "problem": reason or None,
                        "superseded": "older store format" in reason})
        return out
    finally:
        conn.close()


def _replay(snapshot: dict | None, events) -> dict:
    mem = sqlite3.connect(":memory:")
    structure.create(mem)
    if snapshot:
        for table in structure.TABLES:
            rows = snapshot.get(table, [])
            if rows:
                mem.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(rows[0]))})", rows)
    for ev in events:
        structure.apply(mem, ev, strict=False)
    return structure.snapshot(mem)


def _replace_tables(conn, tables: dict) -> None:
    """Overwrite structure tables with recovered contents (the log itself is never touched)."""
    conn.execute("BEGIN IMMEDIATE")
    for table, rows in tables.items():
        for action in ("update", "delete"):
            conn.execute(f"DROP TRIGGER IF EXISTS {table}_append_only_{action}")
        conn.execute(f"DELETE FROM {table}")
        if rows:
            conn.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(rows[0]))})", rows)
    conn.execute("COMMIT")
    structure.create(conn)   # puts the append-only triggers back


def recover(store, reconciler=None) -> dict:
    """Rebuild state from the newest valid checkpoint plus replay; repair structure only where it differs."""
    conn = store._connect()
    try:
        problems, used = [], None
        snapshot = None
        for row in conn.execute("SELECT * FROM checkpoints ORDER BY checkpoint_id DESC").fetchall():
            ok, reason, snap = check_checkpoint(store, conn, row)
            if ok:
                used, snapshot = {"checkpoint_id": row[0], "log_position": row[1]}, snap
                break
            problems.append(reason)
        stored = structure.snapshot(conn)
    finally:
        conn.close()
    start = used["log_position"] if used else 0
    replayed = [ev for ev in store.events() if ev.log_position > start]
    recovered = _replay(snapshot, replayed)
    repaired = [t for t in structure.TABLES if stored[t] != recovered[t]]
    if repaired:
        conn = store._connect()
        try:
            _replace_tables(conn, {t: recovered[t] for t in repaired})
        finally:
            conn.close()
    derived = store.rebuild_derived()
    reconciled = None
    if reconciler is not None:
        result = reconciler.run()
        reconciled = {"changes": len(result.changes), "conflicts": len(result.conflicts)}
    report = {"checkpoint": used, "replayed_events": len(replayed), "repaired_tables": repaired,
              "skipped_checkpoints": problems, "derived": derived, "reconciled": reconciled}
    from agent_memory.schema import EventInput
    store.append(EventInput(kind="recovery", session_id="engine", writer_id="engine-recovery",
                            summary_fields={k: v for k, v in report.items() if k != "derived"}))
    return report
