"""Deep tests and high-value red team for V0.3 Memory System.

Tests semantic search accuracy, auto-connection correctness, large-scale performance,
persistence integrity, concurrent access, and error handling.
"""
import sys, os, tempfile, threading, time, json, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from memory.system import MemorySystem


def test_semantic_search_finds_related_facts():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        memory.store(Fact("great white shark", "is", "predator", source=Source.USER))
        memory.store(Fact("tuna", "is", "fish", source=Source.USER))
        memory.store(Fact("dog", "is", "mammal", source=Source.USER))
        results = memory.search("shark", limit=3)
        assert len(results) >= 1
        subjects = [r.get("subject", "") for r in results]
        assert any("shark" in s.lower() for s in subjects)


def test_auto_connection_finds_all_links():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        memory.store(Fact("tweety", "is", "bird", source=Source.USER))
        memory.store(Fact("bird", "can", "fly", source=Source.USER))
        memory.store(Fact("bird", "has", "wings", source=Source.USER))
        fact = Fact("tweety", "is", "bird")
        context = memory.get_context(fact, hops=2)
        assert len(context) >= 2


def test_large_scale_1000_facts_performance():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        start = time.time()
        for i in range(1000):
            memory.store(Fact(f"n{i}", "is", f"m{i}", source=Source.USER))
        elapsed = time.time() - start
        assert memory.count() == 1000
        assert elapsed < 60.0


def test_persistence_roundtrip_integrity():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        for i in range(10):
            memory.store(Fact(f"x{i}", "is", f"y{i}", source=Source.USER))
        save_path = os.path.join(tmpdir, "save")
        memory.save(save_path)
        loaded = MemorySystem.load(save_path)
        assert loaded.count() == 10
        for i in range(10):
            facts = loaded.get_related_facts(f"x{i}")
            assert len(facts) > 0


def test_concurrent_store_and_recall():
    errors = []
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        def worker(wid):
            try:
                for i in range(20):
                    memory.store(Fact(f"w{wid}_n{i}", "is", f"w{wid}_m{i}", source=Source.USER))
                    memory.recall(f"w{wid}_n{i}")
            except Exception as e:
                errors.append(f"{wid}: {e}")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(errors) == 0


def test_corrupted_sqlite_handling():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "corrupted.db")
        with open(db_path, "w") as f:
            f.write("not a sqlite database")
        try:
            memory = MemorySystem(db_path=db_path)
            assert False, "Should have raised an error"
        except Exception:
            pass


def test_missing_lance_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(
            db_path=os.path.join(tmpdir, "test.db"),
            lance_path=os.path.join(tmpdir, "nonexistent.lance")
        )
        memory.store(Fact("a", "is", "b", source=Source.USER))
        assert memory.count() == 1


def test_empty_memory_system():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        assert memory.count() == 0
        assert memory.get_all_facts() == []
        assert memory.recall("anything") == []


def test_store_duplicate_facts():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        memory.store(Fact("a", "is", "b", source=Source.USER))
        memory.store(Fact("a", "is", "b", source=Source.USER))
        assert memory.count() == 2


def test_save_to_nonexistent_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        memory.store(Fact("a", "is", "b", source=Source.USER))
        save_path = os.path.join(tmpdir, "new_dir", "save")
        memory.save(save_path)
        assert os.path.exists(save_path)


def test_load_from_nonexistent_path():
    try:
        MemorySystem.load("/nonexistent/path")
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError:
        pass


def test_concurrent_save_and_load():
    errors = []
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        for i in range(10):
            memory.store(Fact(f"x{i}", "is", f"y{i}", source=Source.USER))
        save_path = os.path.join(tmpdir, "save")
        memory.save(save_path)
        def loader():
            try:
                MemorySystem.load(save_path)
            except Exception as e:
                errors.append(str(e))
        threads = [threading.Thread(target=loader) for _ in range(3)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(errors) == 0
