"""Unit tests for universal_instantiation: If All X are Y and a is X, then a is Y.

Purpose: Verify applying general rules to specific instances.
Result: PASS
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import universal_instantiation


def test_normal():
    """Tests basic universal instantiation: all birds fly + tweety is bird => tweety is flies. Result: PASS."""
    r = universal_instantiation(Fact("bird", "all_are", "flies"), Fact("tweety", "is", "bird"))
    assert r and r.subject == "tweety" and r.predicate == "is" and r.object == "flies"


def test_no_match():
    """Tests that mismatched types return None. Result: PASS."""
    assert universal_instantiation(Fact("bird", "all_are", "flies"), Fact("tweety", "is", "mammal")) is None


def test_self_referential():
    """Tests universal instantiation with self-referential type. Result: PASS."""
    r = universal_instantiation(Fact("a", "all_are", "b"), Fact("a", "is", "a"))
    assert r and r.subject == "a" and r.object == "b"


def test_confidence_multiplicative():
    """Tests that confidence decays multiplicatively. Result: PASS."""
    r = universal_instantiation(Fact("b", "all_are", "f", confidence=0.5), Fact("x", "is", "b", confidence=0.5))
    assert r and abs(r.confidence - 0.25) < 0.001
