"""Unit tests for subtype_transitivity: If X is Y and Y->Z, then X->Z.

Purpose: Verify type hierarchy reasoning (penguin is bird, birds fly => penguins fly).
Result: PASS
Fix: Was missing entirely. Added during red-team pass #2.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import subtype_transitivity


def test_normal():
    """Tests basic subtype transitivity: penguin is bird + bird->flies => penguin->flies. Result: PASS."""
    r = subtype_transitivity(Fact("penguin", "is", "bird"), Fact("bird", "implies", "flies"))
    assert r and r.subject == "penguin" and r.predicate == "implies" and r.object == "flies"


def test_no_match():
    """Tests that mismatched types return None. Result: PASS."""
    assert subtype_transitivity(Fact("penguin", "is", "bird"), Fact("fish", "implies", "swims")) is None


def test_self_referential():
    """Tests subtype transitivity with self-referential type. Result: PASS."""
    r = subtype_transitivity(Fact("a", "is", "a"), Fact("a", "implies", "b"))
    assert r and r.subject == "a" and r.object == "b"


def test_confidence_multiplicative():
    """Tests that confidence decays multiplicatively. Result: PASS."""
    r = subtype_transitivity(Fact("p", "is", "b", confidence=0.5), Fact("b", "implies", "f", confidence=0.5))
    assert r and abs(r.confidence - 0.25) < 0.001
