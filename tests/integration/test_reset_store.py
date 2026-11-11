"""Stage 0.6 (#23): the guarded reset script, on a temporary copy of an old-style store."""
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import backup_stores
import reset_store


@pytest.fixture(autouse=True)
def no_adam_processes(monkeypatch):
    monkeypatch.setattr(reset_store, "adam_processes", lambda: [])


def make_old_stores(root):
    """Stores shaped like the pre-Stage 0.6 production data."""
    with sqlite3.connect(root / "adam_memory.db") as conn:
        conn.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, subject TEXT, predicate TEXT, object TEXT)")
        conn.executemany("INSERT INTO facts (subject, predicate, object) VALUES (?, ?, ?)", [("bird", "can", "fly")] * 3)
        conn.execute("CREATE TABLE eq_state (id INTEGER PRIMARY KEY, data TEXT)")
        conn.execute("INSERT INTO eq_state (data) VALUES ('{}')")
    versions = root / "adam_vectors.lance" / "facts.lance" / "_versions"
    versions.mkdir(parents=True)
    for i in range(5):
        (versions / f"{i}.manifest").write_bytes(b"manifest" * 100)
    (root / "adam_save").mkdir()
    (root / "adam_save" / "graph.json").write_text("{}")


def test_without_yes_nothing_changes(tmp_path, capsys):
    make_old_stores(tmp_path)
    before = backup_stores.current_hashes(str(tmp_path))
    assert reset_store.reset(str(tmp_path), yes=False) == 2
    assert backup_stores.current_hashes(str(tmp_path)) == before
    assert not (tmp_path / "backups").exists()
    assert "Dry run" in capsys.readouterr().out


def test_reset_backs_up_then_creates_fresh_empty_stores(tmp_path):
    make_old_stores(tmp_path)
    before = backup_stores.current_hashes(str(tmp_path))
    assert reset_store.reset(str(tmp_path), yes=True) == 0

    backups = list((tmp_path / "backups").iterdir())
    assert len(backups) == 1
    manifest = json.loads((backups[0] / "MANIFEST.json").read_text())
    recorded = {k: v for store in manifest["stores"].values() for k, v in store["hashes"].items()}
    assert recorded == before
    assert backup_stores.current_hashes(str(backups[0])) == before  # the backup opens and matches

    assert not (tmp_path / "adam_vectors.lance").exists()
    assert not (tmp_path / "adam_save").exists()
    with sqlite3.connect(tmp_path / "adam_memory.db") as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2  # schema 2: derivations (Stage 1.4)
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "eq_state" not in tables
    with sqlite3.connect(tmp_path / "adam_vectors.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] == 0  # no placeholder row
        meta = dict(conn.execute("SELECT key, value FROM meta"))
    assert {"schema_version", "embedding_model", "embedding_dim", "created_at"} <= set(meta)
    assert os.path.getsize(tmp_path / "adam_vectors.db") < 10_000_000
    assert not (tmp_path / "skills").exists()


def test_reset_is_idempotent(tmp_path):
    make_old_stores(tmp_path)
    assert reset_store.reset(str(tmp_path), yes=True) == 0
    after_first = backup_stores.current_hashes(str(tmp_path))
    assert reset_store.reset(str(tmp_path), yes=True) == 0
    assert backup_stores.current_hashes(str(tmp_path)) == after_first
    assert len(list((tmp_path / "backups").iterdir())) == 1  # no second backup of empty stores


def test_existing_matching_backup_is_reused(tmp_path):
    make_old_stores(tmp_path)
    assert backup_stores.backup(str(tmp_path), str(tmp_path / "backups" / "earlier")) == 0
    assert reset_store.reset(str(tmp_path), yes=True) == 0
    assert [p.name for p in (tmp_path / "backups").iterdir()] == ["earlier"]


def test_reset_refuses_while_adam_is_running(tmp_path, monkeypatch):
    make_old_stores(tmp_path)
    monkeypatch.setattr(reset_store, "adam_processes", lambda: ["123: python -m interface.web.app"])
    before = backup_stores.current_hashes(str(tmp_path))
    assert reset_store.reset(str(tmp_path), yes=True) == 1
    assert backup_stores.current_hashes(str(tmp_path)) == before


def test_fresh_stores_work_with_adam(tmp_path):
    make_old_stores(tmp_path)
    reset_store.reset(str(tmp_path), yes=True)
    from memory.system import MemorySystem
    memory = MemorySystem(db_path=str(tmp_path / "adam_memory.db"), lance_path=str(tmp_path / "adam_vectors.db"))
    memory.store(__import__("kernel.facts", fromlist=["Fact"]).Fact("cat", "is", "animal"))
    assert memory.count() == 1 and memory.semantic.count() == 1
