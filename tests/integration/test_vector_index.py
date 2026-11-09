"""The semantic index chosen in Stage 0.5 (#32): bounded growth, rebuild, and clear errors."""
import os

import pytest

from kernel.facts import Fact, Source
from memory.semantic_index import SemanticIndex, model_cache_dir
from memory.system import MemorySystem

# Recorded limit for 1,000 facts at 384 dimensions (benchmark: about 2.1 MB).
DISK_LIMIT_BYTES = 4_000_000


def store_files(tmp_path):
    return sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("vectors"))


def test_1000_unique_facts_stay_under_the_recorded_disk_limit(tmp_path):
    memory = MemorySystem(db_path=str(tmp_path / "facts.db"), lance_path=str(tmp_path / "vectors.db"))
    for i in range(1000):
        memory.store(Fact(f"thing{i}", "is", f"kind{i % 23}", source=Source.USER))
    assert memory.semantic.count() == 1000
    assert os.path.getsize(tmp_path / "vectors.db") < DISK_LIMIT_BYTES
    assert store_files(tmp_path) == ["vectors.db"]  # one file, no version history


def test_rewriting_the_same_fact_id_never_grows_the_index(tmp_path):
    index = SemanticIndex(str(tmp_path / "vectors.db"))
    fact = Fact("bird", "can", "fly", source=Source.USER)
    index.store(1, fact)
    size = os.path.getsize(tmp_path / "vectors.db")
    for _ in range(50):
        index.store(1, fact)
    assert index.count() == 1
    assert os.path.getsize(tmp_path / "vectors.db") == size


def test_index_can_be_rebuilt_from_the_fact_store(tmp_path):
    memory = MemorySystem(db_path=str(tmp_path / "facts.db"), lance_path=str(tmp_path / "vectors.db"))
    for i in range(30):
        memory.store(Fact(f"thing{i}", "is", "animal", source=Source.USER))
    memory.semantic.close()
    os.remove(tmp_path / "vectors.db")
    rebuilt = MemorySystem(db_path=str(tmp_path / "facts.db"), lance_path=str(tmp_path / "vectors.db"))
    assert rebuilt.semantic.count() == 0
    assert rebuilt.rebuild_index() == rebuilt.count() == 30
    assert rebuilt.search("thing7 is animal", limit=1)[0]["subject"] == "thing7"


def test_search_returns_closest_facts_with_their_fields(tmp_path):
    index = SemanticIndex(str(tmp_path / "vectors.db"))
    index.store(1, Fact("shark", "is", "fish", source=Source.USER))
    index.store(2, Fact("eagle", "is", "bird", source=Source.USER))
    results = index.search("eagle is bird", limit=2)
    assert [r["id"] for r in results] == ["2", "1"]
    assert {"subject", "predicate", "object", "confidence", "source", "timestamp", "_distance"} <= set(results[0])
    assert index.search("anything", limit=0) == []


def test_empty_index_returns_no_results(tmp_path):
    assert SemanticIndex(str(tmp_path / "vectors.db")).search("anything") == []


def test_changed_embedding_model_gives_a_clear_error(tmp_path):
    index = SemanticIndex(str(tmp_path / "vectors.db"))
    index.store(1, Fact("a", "is", "b"))
    index._embed = lambda text: [1.0] * 256
    with pytest.raises(RuntimeError, match="rebuild the index"):
        index.search("a is b")


def test_old_lancedb_directory_is_rejected_with_a_clear_error(tmp_path):
    old = tmp_path / "adam_vectors.lance"
    old.mkdir()
    with pytest.raises(RuntimeError, match="old LanceDB store"):
        SemanticIndex(str(old))


def test_model_cache_survives_restarts(monkeypatch):
    monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    assert model_cache_dir() == os.path.join(os.path.expanduser("~"), ".cache", "fastembed")
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", "/data/models")
    assert model_cache_dir() == "/data/models"
