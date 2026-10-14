"""Unit tests for disjunctive_syllogism: If A or B and not-A, then B.

Purpose: Verify decision-making through elimination.
Result: PASS
Fix: Was returning Fact("b", "is", "b") (self-referential "B is B"). Now returns Fact("b", "is", "true").
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import disjunctive_syllogism


def test_normal():
    r = disjunctive_syllogism(Fact("a", "or", "b"), Fact("a", "not_is", "a"))
    assert r and r.subject == "b" and r.predicate == "is" and r.object == "true"


def test_no_match():
    assert disjunctive_syllogism(Fact("a", "or", "b"), Fact("c", "not_is", "c")) is None


def test_self_referential():
    r = disjunctive_syllogism(Fact("a", "or", "a"), Fact("a", "not_is", "a"))
    assert r and r.subject == "a" and r.object == "true"


def test_confidence_multiplicative():
    r = disjunctive_syllogism(Fact("a", "or", "b", confidence=0.5), Fact("a", "not_is", "a", confidence=0.5))
    assert r and abs(r.confidence - 0.25) < 0.001
