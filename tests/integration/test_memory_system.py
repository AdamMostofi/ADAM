"""Integration tests for the complete MemorySystem.

Purpose: Verify all 3 layers work together (exact, semantic, connection graph).
Result: PASS
"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from memory.system import MemorySystem


def test_store_and_recall():
    """Tests storing a fact and recalling it by text search. Result: PASS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        system = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        fact = Fact("tweety", "is", "bird", source=Source.USER)
        system.store(fact)
        results = system.recall("tweety")
        assert len(results) > 0
        assert any(f.subject == "tweety" for f in results)


def test_store_multiple_and_count():
    """Tests storing multiple facts and counting them. Result: PASS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        system = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        system.store(Fact("a", "is", "b", source=Source.USER))
        system.store(Fact("c", "is", "d", source=Source.USER))
        assert system.count() == 2


def test_get_context():
    """Tests retrieving related facts via connection graph. Result: PASS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        system = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        system.store(Fact("tweety", "is", "bird", source=Source.USER))
        system.store(Fact("bird", "can", "fly", source=Source.USER))
        fact = Fact("tweety", "is", "bird")
        context = system.get_context(fact, hops=1)
        assert len(context) > 0


def test_auto_connect():
    """Tests automatic connection between related facts. Result: PASS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        system = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        system.store(Fact("a", "is", "b", source=Source.USER))
        system.store(Fact("b", "is", "c", source=Source.USER))
        related = system.graph.get_related("a", hops=2)
        assert len(related) > 0


def test_save_and_load():
    """Tests persistence roundtrip (save then load). Result: PASS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        system = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        system.store(Fact("x", "is", "y", source=Source.USER))
        system.store(Fact("y", "is", "z", source=Source.USER))
        save_path = os.path.join(tmpdir, "save")
        system.save(save_path)
        loaded = MemorySystem.load(save_path, lance_path=os.path.join(save_path, "vectors.lance"))
        assert loaded.count() == 2


def test_engine_integration():
    """Tests that MemorySystem works with InferenceEngine. Result: PASS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        system = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        system.engine.add_facts([
            Fact("bird", "all_are", "flies", source=Source.USER),
            Fact("tweety", "is", "bird", source=Source.USER),
        ])
        system.engine.infer()
        for belief in system.engine.query():
            system.store(belief.fact)
        assert system.count() > 0


def test_get_related_facts():
    """Tests retrieving all facts with same subject. Result: PASS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        system = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        system.store(Fact("cat", "is", "mammal", source=Source.USER))
        system.store(Fact("cat", "is", "pet", source=Source.USER))
        related = system.get_related_facts("cat")
        assert len(related) == 2
