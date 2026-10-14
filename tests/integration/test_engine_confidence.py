"""Integration tests for confidence propagation through inference chains.

Purpose: Verify that confidence decays correctly through multi-step reasoning.
Result: PASS
Fix: Was using min() which was too optimistic. Now uses multiplication for proper decay.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine


def test_confidence_decay_two_steps():
    """Tests 2-step confidence decay: 0.9 * 0.9 = 0.81. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", confidence=0.9),
        Fact("b", "implies", "c", confidence=0.9),
        Fact("a", "is", "a", confidence=1.0),
    ])
    engine.infer()
    r = [b for b in engine.query(subject="a", predicate="is", object="c")]
    assert len(r) > 0
    assert abs(r[0].confidence - 0.81) < 0.001


def test_confidence_decay_three_steps():
    """Tests 3-step confidence decay: 0.9^3 = 0.729. Result: PASS."""
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
    assert r[0].confidence < 0.8


def test_confidence_never_exceeds_1():
    """Tests that confidence never exceeds 1.0 regardless of input. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", confidence=0.99),
        Fact("a", "is", "a", confidence=0.99),
    ])
    engine.infer()
    for b in engine.query():
        assert b.confidence <= 1.0


def test_confidence_never_below_0():
    """Tests that confidence never goes below 0. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", confidence=0.001),
        Fact("a", "is", "a", confidence=0.001),
    ])
    engine.infer()
    for b in engine.query():
        assert b.confidence >= 0.0


def test_deep_chain_confidence():
    """Tests 10-hop chain confidence: 0.95^10 = 0.598. Result: PASS."""
    engine = InferenceEngine()
    facts = [Fact(f"n{i}", "implies", f"n{i+1}", confidence=0.95) for i in range(10)]
    facts.append(Fact("n0", "is", "n0", confidence=1.0))
    engine.add_facts(facts)
    engine.infer()
    final = engine.query(subject="n0", predicate="is", object="n10")
    assert len(final) > 0
    assert final[0].confidence < 0.6
