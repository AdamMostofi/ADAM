"""Stage 0.6 (#23): one row and one vector per fact, schema version, and index metadata."""
import sqlite3
import time

import pytest

from kernel.facts import Fact, Source
from memory.exact_store import ExactStore, OldSchemaError, SCHEMA_VERSION
from memory.semantic_index import EMBEDDING_DIM, IndexMismatchError, SemanticIndex
from memory.system import MemorySystem


def make_memory(tmp_path):
    return MemorySystem(db_path=str(tmp_path / "facts.db"), lance_path=str(tmp_path / "vectors.db"))


def test_same_fact_stored_ten_times_is_one_row_and_one_vector(tmp_path):
    memory = make_memory(tmp_path)
    ids = {memory.store(Fact("bird", "can", "fly", source=Source.USER)) for _ in range(10)}
    assert len(ids) == 1
    assert memory.count() == 1
    assert memory.semantic.count() == 1


def test_same_fact_from_a_different_source_is_a_second_row(tmp_path):
    memory = make_memory(tmp_path)
    memory.store(Fact("bird", "can", "fly", source=Source.USER))
    memory.store(Fact("bird", "can", "fly", source=Source.INFERRED))  # derived facts need derivations (1.4)
    assert memory.count() == 2
    assert memory.semantic.count() == 2


def test_case_and_spacing_do_not_create_duplicates(tmp_path):
    memory = make_memory(tmp_path)
    memory.store(Fact("bird", "can", "fly", source=Source.USER))
    memory.store(Fact("  Bird ", "CAN", "fly", source=Source.USER))
    assert memory.count() == 1


def test_duplicate_keeps_higher_confidence_and_newer_timestamp(tmp_path):
    store = ExactStore(str(tmp_path / "facts.db"))
    first = store.store(Fact("a", "is", "b", confidence=0.9, timestamp=100.0))
    second = store.store(Fact("a", "is", "b", confidence=0.5, timestamp=200.0))
    assert first == second
    fact = store.get(first)
    assert fact.confidence == 0.9
    assert fact.timestamp == 200.0
    store.store(Fact("a", "is", "b", confidence=0.95, timestamp=150.0))
    fact = store.get(first)
    assert fact.confidence == 0.95
    assert fact.timestamp == 200.0


def test_duplicate_does_not_add_graph_edges(tmp_path):
    memory = make_memory(tmp_path)
    for _ in range(3):
        memory.store(Fact("cat", "is", "animal", source=Source.USER))
    edges = [e for e in memory.graph.get_all_edges() if e[2].get("predicate") == "is"]
    assert len(edges) == 1


def test_fact_store_records_schema_version(tmp_path):
    store = ExactStore(str(tmp_path / "facts.db"))
    with sqlite3.connect(tmp_path / "facts.db") as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    meta = store.meta()
    assert meta["schema_version"] == str(SCHEMA_VERSION)
    assert meta["created_at"]


def test_old_fact_schema_gives_a_clear_reset_message(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, subject TEXT, predicate TEXT, object TEXT)")
    with pytest.raises(OldSchemaError, match="reset_store.py"):
        ExactStore(str(path))


def test_index_meta_records_model_dimension_schema_and_time(tmp_path):
    index = SemanticIndex(str(tmp_path / "vectors.db"))
    meta = index.meta()
    assert meta["embedding_model"] == index.model_name
    assert meta["embedding_dim"] == str(EMBEDDING_DIM)
    assert meta["schema_version"] == "1"
    assert meta["created_at"]


def test_index_built_with_another_model_fails_fast_and_can_be_rebuilt(tmp_path):
    memory = make_memory(tmp_path)
    for i in range(5):
        memory.store(Fact(f"thing{i}", "is", "animal", source=Source.USER))
    memory.semantic.close()
    with sqlite3.connect(tmp_path / "vectors.db") as conn:
        conn.execute("UPDATE meta SET value = 'some-older-model' WHERE key = 'embedding_model'")
    reopened = make_memory(tmp_path)
    with pytest.raises(IndexMismatchError, match="Rebuild the index"):
        reopened.semantic.count()
    assert reopened.rebuild_index() == reopened.count() == 5
    assert reopened.semantic.meta()["embedding_model"] == reopened.semantic.model_name


def test_index_with_rows_but_no_metadata_must_be_rebuilt(tmp_path):
    path = tmp_path / "vectors.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE vectors (id TEXT PRIMARY KEY, subject TEXT NOT NULL, predicate TEXT NOT NULL, "
                     "object TEXT NOT NULL, confidence REAL, source TEXT, timestamp REAL, embedding BLOB NOT NULL)")
        conn.execute("INSERT INTO vectors VALUES ('1', 'a', 'is', 'b', 1.0, 'user', 0, x'00')")
    with pytest.raises(IndexMismatchError):
        SemanticIndex(str(path)).count()
