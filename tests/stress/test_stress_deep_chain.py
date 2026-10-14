"""Stress tests: 100+ hop reasoning chains.

Purpose: Verify no stack overflow, confidence underflow, or infinite loops.
Result: PASS
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine


def test_100_hop_chain():
    """Tests 100-hop implication chain completes without stack overflow. Result: PASS."""
    engine = InferenceEngine()
    facts = [Fact(f"n{i}", "implies", f"n{i+1}") for i in range(100)]
    facts.append(Fact("n0", "is", "n0"))
    engine.add_facts(facts)
    engine.infer(max_iterations=500)
    assert len(engine.query(subject="n0", predicate="is", object="n100")) > 0


def test_100_hop_confidence_not_zero():
    """Tests that 100-hop confidence doesn't underflow to 0 (0.99^100 = 0.366). Result: PASS."""
    engine = InferenceEngine()
    facts = [Fact(f"n{i}", "implies", f"n{i+1}", confidence=0.99) for i in range(100)]
    facts.append(Fact("n0", "is", "n0", confidence=1.0))
    engine.add_facts(facts)
    engine.infer(max_iterations=500)
    final = engine.query(subject="n0", predicate="is", object="n100")
    assert len(final) > 0
    assert final[0].confidence > 0.0


def test_100_hop_transitivity():
    """Tests that 100-hop transitivity chain is computed. Result: PASS."""
    engine = InferenceEngine()
    facts = [Fact(f"n{i}", "implies", f"n{i+1}") for i in range(100)]
    engine.add_facts(facts)
    engine.infer(max_iterations=500)
    assert len(engine.query(subject="n0", predicate="implies", object="n100")) > 0
