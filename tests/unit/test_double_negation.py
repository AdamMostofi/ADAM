"""Unit tests for double_negation: NOT(NOT P) => P.

Purpose: Verify negation elimination.
Result: PASS
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import double_negation


def test_normal():
    r = double_negation(Fact("p", "not_not", "true"))
    assert r and r.subject == "p" and r.predicate == "is" and r.object == "true"


def test_wrong_predicate():
    assert double_negation(Fact("p", "is", "true")) is None


def test_self_referential():
    r = double_negation(Fact("a", "not_not", "a"))
    assert r and r.subject == "a" and r.object == "a"


def test_confidence_preserved():
    r = double_negation(Fact("p", "not_not", "true", confidence=0.8))
    assert r and r.confidence == 0.8
