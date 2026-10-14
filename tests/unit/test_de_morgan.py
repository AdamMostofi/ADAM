"""Unit tests for De Morgan's Laws: NOT(A AND B) => NOT A, NOT B; NOT(A OR B) => NOT A, NOT B.

Purpose: Verify negation distribution over logical connectives.
Result: PASS
Fix: Was returning string descriptions like "(a or b)" that couldn't be used in further inference. Now returns actual Fact objects with not_is predicates.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import de_morgan_and, de_morgan_or


def test_de_morgan_and():
    results = de_morgan_and(Fact("a", "not_and", "b"))
    assert len(results) == 2
    assert all(r.predicate == "not_is" for r in results)


def test_de_morgan_or():
    results = de_morgan_or(Fact("a", "not_or", "b"))
    assert len(results) == 2
    assert all(r.predicate == "not_is" for r in results)


def test_wrong_predicate_returns_empty():
    assert de_morgan_and(Fact("a", "is", "b")) == []
    assert de_morgan_or(Fact("a", "is", "b")) == []


def test_self_referential():
    results = de_morgan_and(Fact("a", "not_and", "a"))
    assert len(results) == 2


def test_confidence_preserved():
    results = de_morgan_and(Fact("a", "not_and", "b", confidence=0.7))
    assert all(r.confidence == 0.7 for r in results)
