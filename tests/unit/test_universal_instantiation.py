"""Unit tests for universal_instantiation: If All X are Y and a is X, then a is Y.

Purpose: Verify applying general rules to specific instances.
Result: PASS
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import universal_instantiation


def test_normal():
    r = universal_instantiation(Fact("bird", "all_are", "flies"), Fact("tweety", "is", "bird"))
    assert r and r.subject == "tweety" and r.predicate == "is" and r.object == "flies"


def test_no_match():
    assert universal_instantiation(Fact("bird", "all_are", "flies"), Fact("tweety", "is", "mammal")) is None


def test_self_referential():
    r = universal_instantiation(Fact("a", "all_are", "b"), Fact("a", "is", "a"))
    assert r and r.subject == "a" and r.object == "b"


def test_confidence_multiplicative():
    r = universal_instantiation(Fact("b", "all_are", "f", confidence=0.5), Fact("x", "is", "b", confidence=0.5))
    assert r and abs(r.confidence - 0.25) < 0.001
