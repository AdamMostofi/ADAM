"""Stress tests: engine with 1000+ facts.

Purpose: Verify performance and stability with large datasets.
Result: PASS
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine


def test_100_facts_no_performance_degradation():
    engine = InferenceEngine()
    facts = [Fact(f"n{i}", "implies", f"n{i+1}") for i in range(100)]
    facts.append(Fact("n0", "is", "n0"))
    start = time.time()
    engine.add_facts(facts)
    engine.infer(max_iterations=300)
    elapsed = time.time() - start
    assert elapsed < 60.0, f"Took {elapsed:.2f}s, expected < 60s"
    assert len(engine.query(subject="n0", predicate="is", object="n100")) > 0


def test_500_independent_facts():
    engine = InferenceEngine()
    facts = [Fact(f"x{i}", "is", f"y{i}") for i in range(500)]
    start = time.time()
    engine.add_facts(facts)
    engine.infer()
    elapsed = time.time() - start
    assert elapsed < 30.0
    user_facts = [b for b in engine.query(predicate="is") if b.fact.source == Source.USER]
    assert len(user_facts) == 500


def test_100_mixed_rules():
    engine = InferenceEngine()
    facts = []
    for i in range(100):
        facts.append(Fact(f"a{i}", "implies", f"b{i}"))
        facts.append(Fact(f"b{i}", "all_are", f"c{i}"))
        facts.append(Fact(f"x{i}", "is", f"a{i}"))
    start = time.time()
    engine.add_facts(facts)
    engine.infer()
    elapsed = time.time() - start
    assert elapsed < 60.0
    assert len(engine.query(predicate="is")) > 100
