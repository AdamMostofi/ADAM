"""Stage 2.11 (#76): purge, tiered lossless compression, storage reporting, export, quick verify, batch appends."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from agent_memory import EventInput, SchemaError, Store, storage
from agent_memory.archive import CorruptObject
from agent_memory.cli import main as amem

S, W = "s1", "w1"
# A leaked secret the scanner can't recognise: low entropy, no known format. Assembled at run time.
SECRET = "hunter2" + "-correct-horse-" + "battery-staple"


def ev(kind="note", session=S, **kw):
    return EventInput(kind=kind, session_id=session, writer_id=W, **kw)


def put(store, path, text, session=S):
    return store.append(ev("file_change", session, payload=text.encode() if isinstance(text, str) else text,
                           summary_fields={"path": path}, path=path))


def raw_files(store) -> bytes:
    return b"".join(p.read_bytes() for p in sorted(Path(store.path).rglob("*")) if p.is_file())


def every_plaintext(store) -> bytes:
    """Everything the store can decrypt or read: loose objects, packed objects, and every database row."""
    out = [store.archive.get(oid) for oid in store.archive.ids()]
    conn = sqlite3.connect(store.path / "memory.db")
    try:
        cold = [r[0] for r in conn.execute("SELECT object_id FROM cold_objects")]
        out += ["\n".join(conn.iterdump()).encode()]
    finally:
        conn.close()
    out += [store.archive.get(oid) for oid in cold]
    return b"\n".join(out)


# ---------------------------------------------------------------- purge
def leak_everywhere(store) -> dict:
    """The secret in a file, a tool result, a message, a knowledge entry, a context packet, a pack and a checkpoint."""
    h = {}
    h["file"] = put(store, "deploy/config.ini", f"[db]\nuser = app\npassphrase = {SECRET}\nhost = db.local\n")
    h["tool"] = store.append(ev("tool_result", summary_fields={"tool": "Bash", "text": f"connected with {SECRET}"},
                                payload=f"$ psql\nusing {SECRET}\nok\n".encode()))
    h["message"] = store.append(ev("user_message", summary_fields={"text": f"the db password is {SECRET}"}))
    h["entry"] = store.declare_entry("discovery", "the db password", S, W, topic="ops", body=f"it is {SECRET}")
    h["packet"] = store.context.load(S, h["entry"], 2)
    old = put(store, "notes/old.txt", f"an old note mentioning {SECRET}\n")
    store.compress(object_ids=[old.payload_object])   # this copy is in a cold pack
    put(store, "notes/clean.txt", "nothing secret here\n")
    store.append(ev("session_end"))                     # a checkpoint whose snapshot holds the entry body
    assert store.knowledge.find(text="hunter2")         # findable before the purge
    assert SECRET.encode() in every_plaintext(store)
    return h


def test_a_purged_value_is_gone_from_every_byte_and_history_stays_connected(store):
    h = leak_everywhere(store)
    events_before = store.count()
    result = store.purge(value=SECRET, reason="leaked db password")
    assert result["objects"] >= 4 and result["events"] >= 3 and result["packs_rewritten"] == 1
    assert "rotate it at its source" in result["advice"]
    # Gone: from the raw bytes of every file, and from everything the store can decrypt or read.
    assert SECRET.encode() not in raw_files(store)
    assert SECRET.encode() not in every_plaintext(store)
    assert b"hunter2" not in raw_files(store)   # not even one word of it in a full-text index segment
    assert store.knowledge.find(text="hunter2") == [] and store.history.search("hunter2") == []
    # History is still connected: the same events, readable, with a marker where the secret was.
    assert store.count() == events_before + 1
    purge_event = list(store.events())[-1]
    assert purge_event.kind == "purge" and SECRET not in json.dumps(purge_event.summary_fields)
    marker = f"[PURGED:{result['fingerprint'][:12]}]"
    assert marker.encode() in store.payload(h["file"]) and b"host = db.local" in store.payload(h["file"])
    assert marker in store.event(h["message"].event_id).summary_fields["text"]
    assert marker in store.knowledge.open(h["entry"])["attrs"]["body"]
    assert store.history.session(S) and store.knowledge.history_of(h["entry"])["status"] == "current"
    restored = store.context.restore(S, h["packet"]["handle"]) if store.context.ledger(S)[h["packet"]["handle"]].state \
        == "offloaded" else store.context._packet(store.context.ledger(S)[h["packet"]["handle"]],
                                                  store.context._text(store.context.ledger(S)[h["packet"]["handle"]]))
    assert SECRET not in restored["text"]
    for mode in (True, False):
        report = store.verify(full=mode)
        assert report["ok"], report["problems"]
    assert store.verify()["purged_records"] == result["events"]


def test_purging_an_object_or_a_session(store):
    a = put(store, "a.txt", "alpha content\n", session="keep")
    b = put(store, "b.txt", "bravo content\n", session="drop")
    c = store.append(ev("user_message", session="drop", summary_fields={"text": "bravo talk"}))
    store.purge(object_id=a.payload_object, reason="test")
    assert b"alpha" not in store.payload(a) and b"PURGED" in store.payload(a)
    out = store.purge(session_id="drop", reason="whole session")
    assert out["objects"] == 1 and out["events"] == 1
    assert b"bravo" not in every_plaintext(store) and b"bravo" not in raw_files(store)
    assert "PURGED" in store.event(c.event_id).summary_fields["text"]
    assert store.verify()["ok"]
    with pytest.raises(ValueError):
        store.purge(value="abc")                       # too short to purge safely
    with pytest.raises(ValueError):
        store.purge(value=SECRET, session_id="keep")   # one target at a time


def test_rotating_the_data_key_re_encrypts_everything(store):
    e = put(store, "a.txt", "rotate me\n")
    store.compress(object_ids=[put(store, "b.txt", "packed me\n").payload_object])
    old_cipher = store.archive._aead
    counts = store.rotate_data_key()
    assert counts["objects"] >= 1 and counts["packs"] == 1
    blob = store.archive.path(e.payload_object).read_bytes()
    with pytest.raises(Exception):
        old_cipher.decrypt(blob[5:17], blob[17:], e.payload_object.encode())   # the old key no longer opens it
    reopened = Store(store.path, project_id="test-project", min_free_bytes=0)
    assert reopened.payload(e) == b"rotate me\n" and reopened.verify()["ok"]


# ---------------------------------------------------------------- tiered compression
TEXT = "".join(f"line {n}: the refresh token rotates on every use, as decided in session {n % 7}\n" for n in range(200))


def test_compression_is_lossless_smaller_and_reversible(store):
    events = [put(store, f"docs/file{n}.md", TEXT + f"file {n}\n") for n in range(40)]
    before = {e.event_id: store.payload(e) for e in events}
    loose_bytes = sum(store.archive.path(e.payload_object).stat().st_size for e in events)
    out = store.compress(older_than_days=0)
    assert out["packed_objects"] >= 40 and store.archive.ids() == []
    report = store.storage_report()
    assert report["packs"]["objects"] >= 40 and report["packs"]["bytes"] < loose_bytes / 3
    assert {e.event_id: store.payload(e) for e in events} == before          # byte for byte, same ids
    assert store.verify()["ok"] and store.verify(full=False)["ok"]
    assert store.artifacts.search("refresh token")                          # derived indexes still read through
    back = store.decompress(everything=True)
    assert back["restored_objects"] >= 40 and back["packs_removed"] >= 1 and store.archive.pack_ids() == []
    assert {e.event_id: store.payload(e) for e in events} == before
    assert store.verify()["ok"]


def test_only_old_unvisited_content_is_compressed_by_default(store):
    events = [put(store, f"f{n}.txt", f"content {n}\n" * 20) for n in range(6)]
    old = time.time() - 60 * 86400
    for e in events:
        os.utime(store.archive.path(e.payload_object), (old, old))
    store.payload(events[0])                       # read today: a visit
    store.append(ev(summary_fields={"text": "x"}))  # visits are written with the next append
    store.compress()
    assert store.archive.ids() == sorted([events[0].payload_object] + [
        oid for oid in store.archive.ids() if oid not in {e.payload_object for e in events}])
    assert all(store.payload(e) == f"content {n}\n".encode() * 20 for n, e in enumerate(events))


def test_compression_starts_by_itself_past_the_recommended_size(store):
    store.configure(storage={"recommended_bytes": 1, "cold_after_days": 0})
    events = [put(store, f"f{n}.txt", TEXT + str(n)) for n in range(5)]
    assert store.archive.ids()
    store.append(ev("session_end"))   # a checkpoint: storage upkeep runs
    assert not set(e.payload_object for e in events) & set(store.archive.ids())
    assert store.storage_report()["packs"]["objects"] >= 5 and store.verify()["ok"]


def test_compressing_one_session(store):
    a = put(store, "a.txt", TEXT, session="old")
    b = put(store, "b.txt", TEXT + "b", session="new")
    assert store.compress(session_id="old")["packed_objects"] == 1
    assert not store.archive.is_loose(a.payload_object) and store.archive.is_loose(b.payload_object)
    assert store.decompress(session_id="old")["restored_objects"] == 1 and store.archive.is_loose(a.payload_object)


def test_a_crash_in_the_middle_of_compressing_loses_nothing(store):
    events = [put(store, f"f{n}.txt", TEXT + str(n)) for n in range(4)]
    before = {e.event_id: store.payload(e) for e in events}
    # Crash 1: the pack was written but never indexed -> an orphan pack; the loose copies are still there.
    store.archive.write_pack({e.payload_object: store.payload(e) for e in events})
    assert storage.cleanup(store)["packs_removed"] == 1
    # Crash 2: indexed, but the loose copies were never removed -> both exist; reads still work.
    remove = store.archive.remove_loose
    store.archive.remove_loose = lambda oid: None
    store.compress(older_than_days=0)
    store.archive.remove_loose = remove
    assert store.archive.ids() and {e.event_id: store.payload(e) for e in events} == before
    assert storage.cleanup(store)["loose_copies_dropped"] == len(events)
    assert {e.event_id: store.payload(e) for e in events} == before and store.verify()["ok"]


def test_a_damaged_pack_is_reported(store):
    e = put(store, "a.txt", TEXT)
    store.compress(older_than_days=0)
    pack = store.archive.pack_path(store.archive.pack_ids()[0])
    data = bytearray(pack.read_bytes())
    data[-1] ^= 1
    pack.write_bytes(bytes(data))
    store.archive._pack_cache.clear()
    with pytest.raises(CorruptObject):
        store.payload(e)
    assert any(p["type"] == "object_problem" for p in store.verify()["problems"])


# ---------------------------------------------------------------- reporting and backups
def test_size_and_growth_are_reported_and_thresholds_warn(store):
    put(store, "a.txt", TEXT)
    conn = sqlite3.connect(store.path / "memory.db")
    conn.execute("INSERT INTO storage_samples VALUES (?, ?)", ("2000-01-01T00:00:00+00:00", 1))
    conn.execute("INSERT INTO storage_samples VALUES (datetime('now', '-2 days'), 1000)")
    conn.commit()
    conn.close()
    r = store.storage_report()
    assert r["total_bytes"] > 0 and r["database_bytes"] > 0 and r["loose_objects"]["count"] >= 1
    assert r["growth"] and r["growth"]["bytes_per_day"] > 0 and r["warnings"] == []
    store.configure(storage={"recommended_bytes": 10, "warn_bytes": 10 ** 12})
    assert "recommended" in store.storage_report()["warnings"][0]
    store.configure(storage={"warn_bytes": 10})
    assert "warning threshold" in store.storage_report()["warnings"][0]
    assert store.count() >= 1 and store.archive.ids()   # reporting never deletes anything


def test_export_and_import_round_trip(store, tmp_path):
    e = put(store, "a.txt", "keep me safe\n")
    store.compress(object_ids=[put(store, "b.txt", "and me\n").payload_object])
    backup = tmp_path / "backup.tar.gz"
    manifest = store.export(backup)
    assert manifest["events"] == store.count() and manifest["includes_key"] is False
    copy = tmp_path / "restored" / ".agent-memory"
    storage.import_backup(backup, copy)
    restored = Store(copy, project_id="test-project", min_free_bytes=0)   # same key file (same machine)
    assert restored.count() == store.count() and restored.payload(e) == b"keep me safe\n" and restored.verify()["ok"]
    with pytest.raises(ValueError):
        storage.import_backup(backup, copy)    # never over an existing store


def test_an_export_with_the_key_opens_on_another_machine(store, tmp_path, monkeypatch):
    e = put(store, "a.txt", "portable\n")
    backup = tmp_path / "backup.tar.gz"
    assert store.export(backup, include_key=True)["includes_key"] is True
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "other-machine"))
    storage.import_backup(backup, tmp_path / "elsewhere")
    assert Store(tmp_path / "elsewhere", project_id="test-project", min_free_bytes=0).payload(e) == b"portable\n"


# ---------------------------------------------------------------- quick verify (#79)
def test_quick_verify_checks_everything_after_the_newest_checkpoint(store):
    store.checkpoint_every = 100
    for n in range(350):
        store.append(ev(summary_fields={"n": n}, payload=f"payload {n}".encode()))
    quick = store.verify(full=False)
    assert quick["ok"] and quick["mode"].startswith("since checkpoint") and quick["events"] == 50
    conn = sqlite3.connect(store.path / "memory.db")
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='events'").fetchall():
        conn.execute(f"DROP TRIGGER {name}")
    conn.execute("UPDATE events SET summary_fields = '{\"n\":-1}' WHERE log_position = 340")   # after it
    conn.commit()
    conn.close()
    assert any(p["type"] == "record_altered" for p in store.verify(full=False)["problems"])
    assert any(p["type"] == "record_altered" for p in store.verify(full=True)["problems"])


def test_quick_verify_falls_back_to_full_without_a_checkpoint(store):
    store.append(ev())
    assert store.verify(full=False)["mode"] == "full (no valid checkpoint)"


# ---------------------------------------------------------------- batch appends (#89)
def test_a_batch_is_all_or_nothing(store):
    store.append(ev())
    count = store.count()
    with pytest.raises(SchemaError):
        store.append_many([ev(summary_fields={"n": 1}),
                           ev("path", summary_fields={"op": "status", "id": "path:missing", "status": "selected"}),
                           ev(summary_fields={"n": 2})])
    assert store.count() == count
    stored = store.append_many([ev(summary_fields={"n": n}, payload=f"p{n}".encode()) for n in range(50)])
    assert [e.writer_seq for e in stored] == list(range(2, 52)) and store.verify()["ok"]


# ---------------------------------------------------------------- the CLI
def test_cli_storage_purge_export_and_verify(tmp_path, capsys, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    base = ["--project", str(project)]
    assert amem([*base, "declare", "create", "kind=note", f"title=the token is {SECRET}"]) == 0
    capsys.readouterr()
    assert amem([*base, "storage", "report"]) == 0
    assert json.loads(capsys.readouterr().out)["total_bytes"] > 0
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(SECRET.encode() + b"\n")))
    assert amem([*base, "purge", "--value-stdin", "--reason", "test"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["events"] == 1 and SECRET not in json.dumps(out)
    assert SECRET.encode() not in b"".join(p.read_bytes() for p in (project / ".agent-memory").rglob("*") if p.is_file())
    assert amem([*base, "verify", "--full"]) == 0
    capsys.readouterr()
    assert amem([*base, "export", str(tmp_path / "b.tar.gz")]) == 0
    assert json.loads(capsys.readouterr().out)["format"] == "agent-memory-backup/1"
