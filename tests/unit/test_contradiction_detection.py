"""Unit tests for contradiction_detection: If P and not-P both exist, flag it.

Purpose: Verify system detects logical conflicts without crashing.
Result: PASS
Fix: Was checking p.predicate == not_p.predicate (never true for is/not_is pairs). Now checks for is/not_is predicate pairs with matching subject and object.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import contradiction_detection


def test_normal():
    """Tests basic contradiction: x is y + x not_is y => contradiction. Result: PASS."""
    r = contradiction_detection(Fact("x", "is", "y"), Fact("x", "not_is", "y"))
    assert r and r.predicate == "contradiction"


def test_reversed_order():
    """Tests that order doesn't matter: not_is + is also detected. Result: PASS."""
    r = contradiction_detection(Fact("x", "not_is", "y"), Fact("x", "is", "y"))
    assert r and r.predicate == "contradiction"


def test_different_subjects():
    """Tests that different subjects don't trigger contradiction. Result: PASS."""
    assert contradiction_detection(Fact("x", "is", "y"), Fact("z", "not_is", "y")) is None


def test_different_objects():
    """Tests that different objects don't trigger contradiction. Result: PASS."""
    assert contradiction_detection(Fact("x", "is", "y"), Fact("x", "not_is", "z")) is None


def test_same_predicate_not_contradiction():
    """Tests that same predicate (is + is) is not a contradiction. Result: PASS."""
    assert contradiction_detection(Fact("x", "is", "y"), Fact("x", "is", "y")) is None


def test_both_negated_not_contradiction():
    """Tests that both negated (not_is + not_is) is not a contradiction. Result: PASS."""
    assert contradiction_detection(Fact("x", "not_is", "y"), Fact("x", "not_is", "y")) is None


def test_contradiction_confidence_always_1():
    """Tests that contradiction confidence is always 1.0 regardless of input confidence. Result: PASS."""
    r = contradiction_detection(Fact("x", "is", "y", confidence=0.1), Fact("x", "not_is", "y", confidence=0.1))
    assert r and r.confidence == 1.0
