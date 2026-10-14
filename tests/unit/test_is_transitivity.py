"""Unit tests for is_transitivity: If X is Y and Y is Z, then X is Z.

Purpose: Verify transitive inheritance through type hierarchies.
Result: PASS
Fix: Was missing entirely. Added during red-team pass #3.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import is_transitivity
from kernel.engine import InferenceEngine


def test_normal():
    r = is_transitivity(Fact("tweety", "is", "penguin"), Fact("penguin", "is", "bird"))
    assert r and r.subject == "tweety" and r.predicate == "is" and r.object == "bird"


def test_no_match():
    assert is_transitivity(Fact("tweety", "is", "penguin"), Fact("bird", "is", "animal")) is None


def test_self_referential():
    r = is_transitivity(Fact("a", "is", "a"), Fact("a", "is", "a"))
    assert r and r.subject == "a" and r.object == "a"


def test_chain_through_engine():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("tweety", "is", "penguin"),
        Fact("penguin", "is", "bird"),
        Fact("bird", "is", "animal"),
    ])
    engine.infer()
    r = [b for b in engine.query(subject="tweety") if b.fact.predicate == "is" and b.fact.object == "animal"]
    assert len(r) > 0
