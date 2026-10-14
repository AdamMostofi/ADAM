"""Unit tests for transitivity: If P->Q and Q->R, then P->R.

Purpose: Verify rule chaining for multi-step reasoning.
Result: PASS
Fix: Confidence now multiplicative (was min, which was too optimistic).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import transitivity
from kernel.engine import InferenceEngine


def test_normal():
    """Tests basic transitivity: a->b + b->c => a->c. Result: PASS."""
    r = transitivity(Fact("a", "implies", "b"), Fact("b", "implies", "c"))
    assert r and r.subject == "a" and r.predicate == "implies" and r.object == "c"


def test_no_chain():
    """Tests that non-chaining implications return None. Result: PASS."""
    assert transitivity(Fact("a", "implies", "b"), Fact("c", "implies", "d")) is None


def test_self_loop():
    """Tests transitivity with self-loop (a->a + a->a => a->a). Result: PASS."""
    r = transitivity(Fact("a", "implies", "a"), Fact("a", "implies", "a"))
    assert r and r.subject == "a" and r.object == "a"


def test_confidence_multiplicative():
    """Tests that confidence decays multiplicatively (0.5 * 0.5 = 0.25). Result: PASS. Fix: was using min(), now uses multiplication."""
    r = transitivity(Fact("a", "implies", "b", confidence=0.5), Fact("b", "implies", "c", confidence=0.5))
    assert r and abs(r.confidence - 0.25) < 0.001


def test_three_step_chain():
    """Tests 3-step chain confidence: 0.9^3 = 0.729. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", confidence=0.9),
        Fact("b", "implies", "c", confidence=0.9),
        Fact("c", "implies", "d", confidence=0.9),
    ])
    engine.infer()
    r = [b for b in engine.query(subject="a", predicate="implies", object="d")]
    assert len(r) == 1 and abs(r[0].confidence - 0.729) < 0.001


def test_deduced_fact_has_source():
    """Tests that deduced facts have DEDUCED source. Result: PASS."""
    r = transitivity(Fact("a", "implies", "b"), Fact("b", "implies", "c"))
    assert r is not None
    assert r.source == Source.DEDUCED
