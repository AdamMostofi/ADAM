"""Integration tests for thread safety.

Purpose: Verify InferenceEngine is safe for concurrent access via RLock.
Result: PASS
"""
import sys, os, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine


def test_concurrent_add_fact():
    """Tests multiple threads adding facts simultaneously. Result: PASS."""
    errors = []
    engine = InferenceEngine()

    def worker(worker_id):
        try:
            for j in range(50):
                engine.add_fact(Fact(f"w{worker_id}_n{j}", "is", f"w{worker_id}_m{j}"))
        except Exception as e:
            errors.append(f"Worker {worker_id}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(engine.query(predicate="is")) == 250


def test_concurrent_query():
    """Tests multiple threads querying simultaneously. Result: PASS."""
    errors = []
    engine = InferenceEngine()
    engine.add_facts([Fact(f"n{i}", "is", f"m{i}") for i in range(100)])

    def worker():
        try:
            for _ in range(100):
                engine.query(predicate="is")
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0


def test_concurrent_add_and_query():
    """Tests concurrent adds and queries. Result: PASS."""
    errors = []
    engine = InferenceEngine()

    def add_worker():
        try:
            for j in range(50):
                engine.add_fact(Fact(f"shared_n{j}", "is", f"shared_m{j}"))
        except Exception as e:
            errors.append(f"Add: {e}")

    def query_worker():
        try:
            for _ in range(100):
                engine.query(subject="shared_n0")
        except Exception as e:
            errors.append(f"Query: {e}")

    threads = [
        threading.Thread(target=add_worker),
        threading.Thread(target=query_worker),
        threading.Thread(target=query_worker),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0


def test_concurrent_infer():
    """Tests concurrent infer() calls. Result: PASS."""
    errors = []
    engine = InferenceEngine()

    def infer_worker():
        try:
            engine.infer()
        except Exception as e:
            errors.append(str(e))

    engine.add_facts([Fact(f"n{i}", "implies", f"n{i+1}") for i in range(20)])
    threads = [threading.Thread(target=infer_worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
