"""Unit tests for modus_tollens: If P->Q and not-Q, then not-P.

Purpose: Verify debugging/inverse reasoning rule.
Result: PASS
Fix: Was checking not_q.subject == p_implies_q.object (wrong field). Now checks not_q.object == p_implies_q.object (consequent matching).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import modus_tollens


def test_normal():
    r = modus_tollens(Fact("code", "implies", "runs"), Fact("myapp", "not_is", "runs"))
    assert r and r.subject == "myapp" and r.predicate == "not_is" and r.object == "code"
    assert r.source == Source.DEDUCED


def test_no_match_wrong_object():
    assert modus_tollens(Fact("a", "implies", "b"), Fact("x", "not_is", "c")) is None


def test_no_match_wrong_predicate():
    assert modus_tollens(Fact("a", "implies", "b"), Fact("x", "is", "b")) is None


def test_zero_confidence():
    r = modus_tollens(Fact("a", "implies", "b", confidence=0.0), Fact("x", "not_is", "b"))
    assert r and r.confidence == 0.0


def test_self_referential():
    r = modus_tollens(Fact("a", "implies", "a"), Fact("x", "not_is", "a"))
    assert r and r.subject == "x" and r.object == "a"


def test_confidence_decay():
    r = modus_tollens(Fact("a", "implies", "b", confidence=0.5), Fact("x", "not_is", "b", confidence=0.5))
    assert r and r.confidence < 0.25
