"""Storage: tiered lossless compression, visits, purge, key rotation, size reporting, export (Stage 2.11).

**Tiered compression (decision D3).** The store lives inside the project, so
growth is handled by compressing, never by moving or deleting.
- `maybe_compress` runs after checkpoints. Once the store passes its
  recommended size (a setting), loose objects older than `cold_after_days`
  that nobody has read for that long are packed (see archive.py).
- An agent or user can also compress or decompress any part explicitly: by
  session, by time, or by object.
- It is lossless: object ids and content are unchanged, every pack is read
  back and checked before loose copies are removed, and `verify` checks
  packed objects too.
- Visits are recorded in a derived table (`object_access`), never in the
  append-only log. Reads queue them in memory, and they are written at the
  next append, compression or report, so reading never takes a write lock.

**Purge (a leaked secret, an object, or a session).** This is the one
audited way to remove content from an append-only store.
- **Objects:** every object holding the content is replaced by a redacted
  copy (a value purge) or a marker (an object or session purge). Reads of
  the old id are redirected to it, so history stays connected. The original
  is removed from disk, and any pack holding it is rewritten without it.
- **Events:** summary fields holding the value are rewritten to a marker.
  Their stored hashes are kept, so the chains stay intact, and each
  rewritten event is listed, so `verify` reports it as purged rather than
  tampered.
- **Afterwards:** the structure and derived indexes are rebuilt, a fresh
  checkpoint is taken, freed pages are zeroed and the database vacuumed,
  and the data key can be rotated.
- **The record:** a `purge` event records a keyed fingerprint, never the
  value. Rotate the secret at its source too: purging memory doesn't make a
  leaked secret safe again.

**Reporting.** Sizes (database, loose objects, packs), growth over time from
samples, and warnings against thresholds. Nothing is ever deleted
automatically.

**Export.** A consistent backup (`tar.gz`) of the database, objects and
packs. The key is included only when asked.
"""
from __future__ import annotations

import io
import json
import os
import secrets
import shutil
import sqlite3
import tarfile
import tempfile
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_memory import keys, recovery, structure
from agent_memory.archive import CorruptObject
from agent_memory.schema import EventInput

SCHEMA = """
CREATE TABLE IF NOT EXISTS cold_objects (
    object_id TEXT PRIMARY KEY, pack_id TEXT NOT NULL, offset INTEGER NOT NULL, length INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_cold_pack ON cold_objects(pack_id);
CREATE TABLE IF NOT EXISTS object_access (object_id TEXT PRIMARY KEY, last_read TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS storage_samples (at TEXT NOT NULL, total_bytes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS purged_objects (
    object_id TEXT PRIMARY KEY, replacement_id TEXT NOT NULL, purge_event TEXT, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS purged_events (event_id TEXT PRIMARY KEY, purge_fingerprint TEXT NOT NULL, at TEXT NOT NULL);
"""
DEFAULT_STORAGE = {"recommended_bytes": 1 << 30, "warn_bytes": 5 << 30, "cold_after_days": 30,
                   "pack_bytes": 4 << 20}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def settings(store) -> dict:
    merged = dict(DEFAULT_STORAGE)
    merged.update(store.settings.get("storage") or {})
    return merged


# ------------------------------------------------------------ wiring
def attach(store) -> None:
    """Create the tables and connect the archive to the cold index, purge redirects and visit tracking."""
    conn = store._connect()
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
    store._visits = set()
    archive = store.archive

    def lookup(oid: str):
        conn = store._connect()
        try:
            row = conn.execute("SELECT pack_id, offset, length FROM cold_objects WHERE object_id = ?", (oid,)).fetchone()
            if row:
                return row
            red = conn.execute("SELECT replacement_id FROM purged_objects WHERE object_id = ?", (oid,)).fetchone()
        finally:
            conn.close()
        if red:
            return ("purged", red[0], 0)
        return None

    def cold_lookup(oid: str):
        found = lookup(oid)
        return None if found is None or found[0] == "purged" else found

    original_get = archive.get

    def get(oid: str) -> bytes:
        found = None if archive.is_loose(oid) else lookup(oid)
        if found and found[0] == "purged":
            return original_get(found[1])   # history stays connected: the redacted copy, under its own id
        return original_get(oid)

    archive.cold_lookup = cold_lookup
    archive.get = get
    archive.on_read = store._visits.add


def flush_visits(store, conn) -> None:
    """Write queued visits (inside the caller's transaction)."""
    if not store._visits:
        return
    now = _now()
    conn.executemany("INSERT OR REPLACE INTO object_access VALUES (?, ?)", [(oid, now) for oid in store._visits])
    store._visits.clear()


def _parse(at: str) -> datetime:
    """An ISO or SQLite timestamp; one without a time zone is UTC."""
    dt = datetime.fromisoformat(at.replace(" ", "T"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def exists(store, oid: str) -> bool:
    if store.archive.is_loose(oid):
        return True
    conn = store._connect()
    try:
        return conn.execute("SELECT 1 FROM cold_objects WHERE object_id = ? UNION SELECT 1 FROM purged_objects "
                            "WHERE object_id = ?", (oid, oid)).fetchone() is not None
    finally:
        conn.close()


# ------------------------------------------------------------ tiered compression
def _scope_ids(store, conn, session_id=None, before=None, object_ids=None) -> set[str] | None:
    """Object ids for an explicit scope, or None for 'everything old and unvisited'."""
    if object_ids:
        return set(object_ids)
    if session_id is None and before is None:
        return None
    sql, args = "SELECT payload_object FROM events WHERE payload_object IS NOT NULL", []
    if session_id:
        sql += " AND session_id = ?"
        args.append(session_id)
    if before:
        sql += " AND recorded_at < ?"
        args.append(before)
    return {r[0] for r in conn.execute(sql, args)}


def compress(store, session_id: str | None = None, before: str | None = None, object_ids=None,
             older_than_days: float | None = None) -> dict:
    """Pack loose objects into the cold tier. Without a scope: objects older and less recently read than the setting."""
    cfg = settings(store)
    cleanup(store)
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        flush_visits(store, conn)
        conn.execute("COMMIT")
        scope = _scope_ids(store, conn, session_id, before, object_ids)
        purged = {r[0] for r in conn.execute("SELECT object_id FROM purged_objects")}
        visits = dict(conn.execute("SELECT object_id, last_read FROM object_access").fetchall())
    finally:
        conn.close()
    days = cfg["cold_after_days"] if older_than_days is None else older_than_days
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff = cutoff_dt.timestamp()
    chosen = []
    for oid in store.archive.ids():
        if oid in purged:
            continue
        if scope is not None:
            if oid in scope:
                chosen.append(oid)
            continue
        old = store.archive.path(oid).stat().st_mtime <= cutoff
        unvisited = oid not in visits or _parse(visits[oid]) <= cutoff_dt
        if old and unvisited:
            chosen.append(oid)
    packed = packs = before_bytes = 0
    batch: dict[str, bytes] = {}
    size = 0

    def write() -> None:
        nonlocal packed, packs, batch, size
        if not batch:
            return
        pack_id, index = store.archive.write_pack(batch)
        conn = store._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany("INSERT OR REPLACE INTO cold_objects VALUES (?, ?, ?, ?)",
                             [(oid, pack_id, off, length) for oid, (off, length) in index.items()])
            conn.execute("COMMIT")
        finally:
            conn.close()
        for oid in index:   # the pack is checked and indexed: only now does the loose copy go
            store.archive.remove_loose(oid)
        packed += len(index)
        packs += 1
        batch, size = {}, 0

    for oid in sorted(chosen):
        before_bytes += store.archive.path(oid).stat().st_size
        content = store.archive.get(oid)
        batch[oid] = content
        size += len(content)
        if size >= cfg["pack_bytes"]:
            write()
    write()
    return {"packed_objects": packed, "packs": packs, "loose_bytes_before": before_bytes}


def decompress(store, session_id: str | None = None, before: str | None = None, object_ids=None,
               everything: bool = False) -> dict:
    """Bring cold objects back to the hot tier (loose files). Packs left empty are removed."""
    conn = store._connect()
    try:
        scope = _scope_ids(store, conn, session_id, before, object_ids)
        rows = conn.execute("SELECT object_id, pack_id FROM cold_objects").fetchall()
    finally:
        conn.close()
    if scope is None and not everything:
        raise ValueError("name a scope (session, before, object ids) or pass everything=True")
    chosen = [(oid, pack) for oid, pack in rows if scope is None or oid in scope]
    for oid, _pack in chosen:
        content = store.archive.get(oid)
        store.archive.remove_loose(oid)
        _write_loose(store, oid, content)
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany("DELETE FROM cold_objects WHERE object_id = ?", [(oid,) for oid, _ in chosen])
        conn.execute("COMMIT")
    finally:
        conn.close()
    removed = cleanup(store)["packs_removed"]
    return {"restored_objects": len(chosen), "packs_removed": removed}


def _write_loose(store, oid: str, content: bytes) -> None:
    """Write a loose copy of an object that may also be indexed cold (put() would skip it)."""
    from agent_memory.archive import MAGIC, _atomic_write
    nonce, sealed = store.archive._encrypt(zlib.compress(content, 6), oid.encode())
    _atomic_write(store.archive.path(oid), MAGIC + nonce + sealed)


def cleanup(store) -> dict:
    """Finish what a crash interrupted: drop loose copies already packed, and packs nothing points to."""
    conn = store._connect()
    try:
        cold = dict(conn.execute("SELECT object_id, pack_id FROM cold_objects").fetchall())
    finally:
        conn.close()
    dropped = 0
    for oid in list(cold):
        if store.archive.is_loose(oid):
            store.archive.remove_loose(oid)
            dropped += 1
    live = set(cold.values())
    removed = 0
    for pack_id in store.archive.pack_ids():
        if pack_id not in live:
            store.archive.delete_pack(pack_id)
            removed += 1
    return {"loose_copies_dropped": dropped, "packs_removed": removed}


def maybe_compress(store) -> dict | None:
    """Compress old, unvisited objects once the store passes its recommended size (never deletes anything)."""
    if report(store, sample=False)["total_bytes"] <= settings(store)["recommended_bytes"]:
        return None
    return compress(store)


# ------------------------------------------------------------ reporting
def _dir_bytes(path: Path) -> tuple[int, int]:
    files = [f for f in path.rglob("*") if f.is_file()] if path.exists() else []
    return len(files), sum(f.stat().st_size for f in files)


def report(store, sample: bool = True) -> dict:
    cfg = settings(store)
    db = store._db
    db_bytes = sum(p.stat().st_size for p in (db, Path(f"{db}-wal"), Path(f"{db}-shm")) if p.exists())
    loose_count, loose_bytes = _dir_bytes(store.archive.root)
    pack_count, pack_bytes = _dir_bytes(store.archive.packs)
    total = db_bytes + loose_bytes + pack_bytes
    conn = store._connect()
    try:
        cold = conn.execute("SELECT COUNT(*) FROM cold_objects").fetchone()[0]
        if sample:
            conn.execute("INSERT INTO storage_samples VALUES (?, ?)", (_now(), total))
        samples = conn.execute("SELECT at, total_bytes FROM storage_samples ORDER BY at").fetchall()
    finally:
        conn.close()
    growth = None
    since = datetime.now(timezone.utc) - timedelta(days=30)
    recent = sorted(((_parse(at), size) for at, size in samples if _parse(at) >= since), key=lambda s: s[0])
    if len(recent) >= 2:
        span = (recent[-1][0] - recent[0][0]).total_seconds() / 86400
        if span > 0:
            growth = {"bytes_per_day": round((recent[-1][1] - recent[0][1]) / span), "window_days": round(span, 2)}
    warnings = []
    if total > cfg["warn_bytes"]:
        warnings.append(f"the store is {total} bytes, over the warning threshold of {cfg['warn_bytes']}; "
                        "consider `amem storage compress`, or moving the project to a larger disk. Nothing is deleted.")
    elif total > cfg["recommended_bytes"]:
        warnings.append(f"the store is {total} bytes, over the recommended {cfg['recommended_bytes']}; old, unvisited "
                        "content is compressed after each checkpoint.")
    return {"path": str(store.path), "total_bytes": total, "database_bytes": db_bytes,
            "loose_objects": {"count": loose_count, "bytes": loose_bytes},
            "packs": {"count": pack_count, "bytes": pack_bytes, "objects": cold},
            "events": store.count(), "growth": growth, "recommended_bytes": cfg["recommended_bytes"],
            "warn_bytes": cfg["warn_bytes"], "warnings": warnings}


# ------------------------------------------------------------ purge
def purge(store, value: bytes | str | None = None, object_id: str | None = None, session_id: str | None = None,
          reason: str = "", rotate_key: bool = False) -> dict:
    """Remove content for good, keep history connected, and record the purge without the content."""
    if sum(x is not None for x in (value, object_id, session_id)) != 1:
        raise ValueError("purge exactly one of: a value, an object id, or a session")
    value = value.encode() if isinstance(value, str) else value
    if value is not None and len(value) < 6:
        raise ValueError("refusing to purge a value shorter than 6 bytes: it would match ordinary text")
    fp = store.scanner.fingerprint(value or (object_id or session_id).encode())
    marker = f"[PURGED:{fp[:12]}]".encode()
    conn = store._connect()
    try:
        if session_id is not None:
            targets = {r[0] for r in conn.execute("SELECT payload_object FROM events WHERE session_id = ? AND "
                                                  "payload_object IS NOT NULL", (session_id,))}
        elif object_id is not None:
            targets = {object_id}
        else:
            targets = None
        cold = dict(conn.execute("SELECT object_id, pack_id FROM cold_objects").fetchall())
        already = {r[0] for r in conn.execute("SELECT object_id FROM purged_objects")}
    finally:
        conn.close()
    # 1. Objects: find them, write their replacements, then remove the originals (rewriting packs that hold any).
    replacements: dict[str, str] = {}
    for oid in sorted(set(store.archive.ids()) | set(cold)):
        if oid in already:
            continue
        if targets is not None and oid not in targets:
            continue
        content = store.archive.get(oid)
        if value is not None:
            if value not in content:
                continue
            replacement = content.replace(value, marker)
        else:
            replacement = marker + b" this content was purged" + (f": {reason}".encode() if reason else b"")
        replacements[oid] = store.archive.put(replacement)
    events = []
    if value is not None or session_id is not None:
        needle = json.dumps(value.decode("utf-8", errors="replace"), ensure_ascii=False)[1:-1] \
            if value is not None else None
        conn = store._connect()
        try:
            for event_id, summary, sess in conn.execute("SELECT event_id, summary_fields, session_id FROM events"):
                if needle and needle in summary:
                    events.append((event_id, summary.replace(needle, marker.decode())))
                elif session_id is not None and sess == session_id:
                    s = json.loads(summary)
                    changed = False
                    for key in ("text", "output", "command", "body"):
                        if isinstance(s.get(key), str) and s[key]:
                            s[key] = marker.decode()
                            changed = True
                    if changed:
                        events.append((event_id, structure.canonical_json(s)))
        finally:
            conn.close()
    at = _now()
    conn = store._connect()
    try:
        conn.execute("PRAGMA secure_delete = ON")
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany("INSERT OR REPLACE INTO purged_objects VALUES (?, ?, NULL, ?)",
                         [(oid, rep, at) for oid, rep in replacements.items()])
        if events:
            conn.execute("DROP TRIGGER IF EXISTS events_append_only_update")
            conn.executemany("UPDATE events SET summary_fields = ? WHERE event_id = ?",
                             [(new, eid) for eid, new in events])
            conn.executemany("INSERT OR REPLACE INTO purged_events VALUES (?, ?, ?)",
                             [(eid, fp, at) for eid, _ in events])
            conn.execute("CREATE TRIGGER IF NOT EXISTS events_append_only_update BEFORE UPDATE ON events "
                         "BEGIN SELECT RAISE(ABORT, 'the event log is append-only'); END")
        conn.execute("COMMIT")
    finally:
        conn.close()
    rewritten_packs = _remove_objects(store, set(replacements), cold)
    # 2. Everything derived from the content: structure, indexes, checkpoints.
    rebuilt = recovery._replay(None, list(store.events()))
    conn = store._connect()
    try:
        recovery._replace_tables(conn, rebuilt)
        # Full-text indexes keep deleted words in their segment tables until merged: drop and recreate them.
        from agent_memory import codegraph, search
        for table in ("artifact_fts", "knowledge_fts", "history_fts"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute("DELETE FROM search_state")
        conn.executescript(codegraph.SCHEMA + search.SCHEMA)
    finally:
        conn.close()
    store.rebuild_derived()
    rotated = rotate_data_key(store) if rotate_key else None
    ev = store.append(EventInput(kind="purge", session_id="engine", writer_id="engine-purge",
                                 summary_fields={"op": "purge", "fingerprint": fp,
                                                 "mode": "value" if value is not None else
                                                 "object" if object_id else "session",
                                                 "objects": len(replacements), "events": len(events),
                                                 "packs_rewritten": rewritten_packs, "reason": reason,
                                                 "key_rotated": bool(rotated)}))
    store.checkpoint(reason="after a purge")
    vacuum(store)
    return {"fingerprint": fp, "objects": len(replacements), "events": len(events), "packs_rewritten": rewritten_packs,
            "key_rotated": rotated, "purge_event": ev.event_id,
            "advice": "Memory no longer holds this content. If it was a secret, rotate it at its source: anything "
                      "that saw it before the purge (backups, other copies, the agent's own logs) may still have it."}


def _remove_objects(store, oids: set[str], cold: dict[str, str]) -> int:
    """Remove originals: loose files go; packs holding any are rewritten without them."""
    for oid in oids:
        store.archive.remove_loose(oid)
    hit = {cold[oid] for oid in oids if oid in cold}
    for pack_id in hit:
        conn = store._connect()
        try:
            rows = conn.execute("SELECT object_id, offset, length FROM cold_objects WHERE pack_id = ?",
                                (pack_id,)).fetchall()
        finally:
            conn.close()
        plain = store.archive.read_pack(pack_id)
        keep = {oid: plain[off:off + length] for oid, off, length in rows if oid not in oids}
        new_id, index = store.archive.write_pack(keep) if keep else (None, {})
        conn = store._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM cold_objects WHERE pack_id = ?", (pack_id,))
            conn.executemany("INSERT INTO cold_objects VALUES (?, ?, ?, ?)",
                             [(oid, new_id, off, length) for oid, (off, length) in index.items()])
            conn.execute("COMMIT")
        finally:
            conn.close()
        store.archive.delete_pack(pack_id)
    return len(hit)


def vacuum(store) -> None:
    """Zero freed pages, rewrite the database, and empty the write-ahead log."""
    conn = sqlite3.connect(store._db, isolation_level=None, timeout=30)
    try:
        conn.execute("PRAGMA secure_delete = ON")
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def rotate_data_key(store) -> dict:
    """Encrypt everything under a new data key. The old key stays readable until every file is rewritten."""
    kek = store._kek
    new_key = secrets.token_bytes(keys.KEY_BYTES)
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        old_blob = conn.execute("SELECT value FROM meta WHERE key = 'data_key'").fetchone()[0]
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('data_key_previous', ?)",
                     (keys.wrap(kek, keys.unwrap(kek, old_blob, "data_key"), "data_key_previous"),))
        conn.execute("UPDATE meta SET value = ? WHERE key = 'data_key'", (keys.wrap(kek, new_key, "data_key"),))
        conn.execute("COMMIT")
    finally:
        conn.close()
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    store.archive._previous = store.archive._aead
    store.archive._aead = AESGCM(new_key)
    counts = store.archive.reencrypt_all()
    conn = store._connect()
    try:
        conn.execute("DELETE FROM meta WHERE key = 'data_key_previous'")
        conn.commit()
    finally:
        conn.close()
    store.archive._previous = None
    return counts


# ------------------------------------------------------------ export and backup
def export(store, destination: str | os.PathLike, include_key: bool = False) -> dict:
    """A consistent backup: database (via SQLite's backup API), objects and packs, in one tar.gz."""
    destination = Path(destination)
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "memory.db"
        src = sqlite3.connect(store._db)
        dst = sqlite3.connect(snapshot)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        manifest = {"format": "agent-memory-backup/1", "created_at": _now(), "project_id": store.project_id,
                    "events": store.count(), "kek_source": _kek_source(store), "includes_key": include_key,
                    "restore": "extract into <project>/.agent-memory (or AMEM_HOME/<project id>); the key file must be "
                               "in $XDG_CONFIG_HOME/agent-memory/keys/ (or AMEM_PASSPHRASE set) to read it"}
        with tarfile.open(destination, "w:gz") as tar:
            data = json.dumps(manifest, indent=2).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            tar.add(snapshot, arcname="memory.db")
            for sub in ("objects", "packs"):
                if (store.path / sub).exists():
                    tar.add(store.path / sub, arcname=sub)
            if include_key and manifest["kek_source"] == "key_file":
                tar.add(store._key_path, arcname=f"keys/{store.project_id}.key")
    return {**manifest, "path": str(destination), "bytes": destination.stat().st_size}


def import_backup(source: str | os.PathLike, store_dir: str | os.PathLike, key_dir: Path | None = None) -> dict:
    """Unpack a backup into an empty store folder. A key inside the backup is installed only if none exists."""
    store_dir = Path(store_dir)
    if store_dir.exists() and any(p.name != ".gitignore" for p in store_dir.iterdir()):
        raise ValueError(f"{store_dir} isn't empty; import into a new store folder")
    store_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(source, "r:gz") as tar:
        manifest = json.loads(tar.extractfile("manifest.json").read())
        for member in tar.getmembers():
            name = member.name
            if name.startswith("/") or ".." in Path(name).parts or not (member.isfile() or member.isdir()):
                raise ValueError(f"refusing an unsafe path in the backup: {name}")
            if name == "manifest.json":
                continue
            if name.startswith("keys/"):
                target = (key_dir or keys.config_dir()) / "keys" / Path(name).name
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with open(target, "wb") as f:
                    f.write(tar.extractfile(member).read())
                os.chmod(target, 0o600)
                continue
            tar.extract(member, store_dir)
    return manifest


def _kek_source(store) -> str:
    conn = store._connect()
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'kek_source'").fetchone()
        return row[0] if row else "unknown"
    finally:
        conn.close()


def purged_report(store) -> dict:
    conn = store._connect()
    try:
        return {"objects": dict(conn.execute("SELECT object_id, replacement_id FROM purged_objects").fetchall()),
                "events": {r[0] for r in conn.execute("SELECT event_id FROM purged_events")}}
    finally:
        conn.close()


def check(store) -> list[dict]:
    """Storage problems for verify: missing packs, purged content still on disk."""
    problems = []
    conn = store._connect()
    try:
        packs = {r[0] for r in conn.execute("SELECT DISTINCT pack_id FROM cold_objects")}
        purged = [r[0] for r in conn.execute("SELECT object_id FROM purged_objects")]
        cold = {r[0] for r in conn.execute("SELECT object_id FROM cold_objects")}
    finally:
        conn.close()
    for pack_id in sorted(packs):
        if not store.archive.pack_path(pack_id).exists():
            problems.append({"type": "storage_problem", "detail": f"pack {pack_id} is missing"})
    for oid in purged:
        if store.archive.is_loose(oid) or oid in cold:
            problems.append({"type": "storage_problem", "detail": f"purged object {oid} is still stored"})
    return problems


__all__ = ["attach", "compress", "decompress", "maybe_compress", "report", "purge", "rotate_data_key", "export",
           "import_backup", "vacuum", "check", "cleanup", "CorruptObject", "shutil"]
