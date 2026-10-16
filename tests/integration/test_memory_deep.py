"""Deep integration tests for V0.3 Memory System.

Verifies semantic search accuracy, auto-connection correctness, and large-scale performance.
"""
import sys, os, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from memory.system import MemorySystem


def test_semantic_search_accuracy():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        memory.store(Fact("great white shark", "is", "predator", source=Source.USER))
        memory.store(Fact("tuna", "is", "fish", source=Source.USER))
        memory.store(Fact("dog", "is", "mammal", source=Source.USER))
        results = memory.search("shark", limit=3)
        assert len(results) >= 1
        subjects = [r.get("subject", "") for r in results]
        assert any("shark" in s.lower() for s in subjects)


def test_auto_connection_correctness():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        memory.store(Fact("tweety", "is", "bird", source=Source.USER))
        memory.store(Fact("bird", "can", "fly", source=Source.USER))
        fact = Fact("tweety", "is", "bird")
        context = memory.get_context(fact, hops=1)
        assert len(context) > 0


def test_memory_count_accuracy():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        for i in range(10):
            memory.store(Fact(f"x{i}", "is", f"y{i}", source=Source.USER))
        assert memory.count() == 10


def test_large_scale_1000_facts():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        start = time.time()
        for i in range(1000):
            memory.store(Fact(f"n{i}", "is", f"m{i}", source=Source.USER))
        elapsed = time.time() - start
        assert memory.count() == 1000
        assert elapsed < 60.0


def test_persistence_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        memory.store(Fact("a", "is", "b", source=Source.USER))
        memory.store(Fact("b", "is", "c", source=Source.USER))
        save_path = os.path.join(tmpdir, "save")
        memory.save(save_path)
        loaded = MemorySystem.load(save_path)
        assert loaded.count() == 2


def test_recall_finds_stored_facts():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        memory.store(Fact("tweety", "is", "bird", source=Source.USER))
        results = memory.recall("tweety")
        assert len(results) > 0
        assert any(f.subject == "tweety" for f in results)
