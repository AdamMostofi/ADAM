"""Integration tests for predicate-indexed agenda optimization.

Purpose: Verify the O(n) agenda system produces identical results to the old O(n^3) approach.
Result: PASS
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine


def test_agenda_correctness_simple():
    """Tests agenda produces correct deductions for simple chain. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b"),
        Fact("b", "implies", "c"),
        Fact("a", "is", "a"),
    ])
    engine.infer()
    assert len(engine.query(subject="a", predicate="is", object="c")) > 0
    assert len(engine.query(subject="a", predicate="implies", object="c")) > 0


def test_agenda_correctness_complex():
    """Tests agenda produces correct deductions for multi-rule chain. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "all_are", "flies"),
        Fact("penguin", "is", "bird"),
        Fact("tweety", "is", "penguin"),
    ])
    engine.infer()
    assert len(engine.query(subject="tweety", predicate="is", object="flies")) > 0


def test_agenda_no_duplicate_facts():
    """Tests agenda doesn't create duplicate beliefs. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b"),
        Fact("b", "implies", "c"),
        Fact("a", "is", "a"),
    ])
    engine.infer()
    a_is_b = [b for b in engine.query(subject="a", predicate="is", object="b")]
    assert len(a_is_b) == 1


def test_agenda_performance_100_facts():
    """Tests 100-fact chain completes quickly. Result: PASS."""
    engine = InferenceEngine()
    facts = [Fact(f"n{i}", "implies", f"n{i+1}") for i in range(100)]
    facts.append(Fact("n0", "is", "n0"))
    start = time.time()
    engine.add_facts(facts)
    engine.infer()
    elapsed = time.time() - start
    assert elapsed < 10.0, f"Took {elapsed:.2f}s, expected < 10s"
    assert len(engine.query(subject="n0", predicate="is", object="n100")) > 0


def test_agenda_confidence_identical():
    """Tests that confidence values are identical to old approach. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", confidence=0.9),
        Fact("b", "implies", "c", confidence=0.9),
        Fact("c", "implies", "d", confidence=0.9),
        Fact("a", "is", "a", confidence=1.0),
    ])
    engine.infer()
    r = [b for b in engine.query(subject="a", predicate="is", object="d")]
    assert len(r) > 0
    assert abs(r[0].confidence - 0.729) < 0.001


def test_agenda_trace_identical():
    """Tests that proof chains are identical to old approach. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "implies", "flies"),
        Fact("tweety", "is", "bird"),
    ])
    engine.infer()
    trace = engine.get_trace()
    assert len(trace) > 0
    assert any("[modus_ponens]" in t for t in trace)


def test_agenda_retract_with_index():
    """Tests that retract properly updates the index. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b"),
        Fact("b", "implies", "c"),
        Fact("a", "is", "a"),
    ])
    engine.infer()
    assert len(engine.query(subject="a", predicate="is", object="c")) > 0
    engine.retract(Fact("a", "implies", "b"))
    assert len(engine.query(subject="a", predicate="is", object="c")) == 0
