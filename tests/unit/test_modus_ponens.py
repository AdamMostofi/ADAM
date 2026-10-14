"""Unit tests for modus_ponens: If P->Q and P, then Q.

Purpose: Verify the #1 reasoning rule (70% of all reasoning).
Result: PASS
Fix: Was checking p_implies_q.object == p.object (wrong field). Now checks p.object == p_implies_q.subject (antecedent matching).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import modus_ponens


def test_normal():
    r = modus_ponens(Fact("bird", "implies", "flies"), Fact("tweety", "is", "bird"))
    assert r and r.subject == "tweety" and r.predicate == "is" and r.object == "flies"
    assert r.source == Source.DEDUCED


def test_no_match_wrong_predicate():
    assert modus_ponens(Fact("a", "implies", "b"), Fact("x", "equals", "a")) is None


def test_no_match_wrong_object():
    assert modus_ponens(Fact("a", "implies", "b"), Fact("x", "is", "c")) is None


def test_zero_confidence():
    r = modus_ponens(Fact("a", "implies", "b", confidence=0.0), Fact("x", "is", "a"))
    assert r and r.confidence == 0.0


def test_full_confidence():
    r = modus_ponens(Fact("a", "implies", "b", confidence=1.0), Fact("x", "is", "a", confidence=1.0))
    assert r and r.confidence == 1.0


def test_confidence_multiplicative():
    r = modus_ponens(Fact("a", "implies", "b", confidence=0.5), Fact("x", "is", "a", confidence=0.5))
    assert r and abs(r.confidence - 0.25) < 0.001


def test_self_referential():
    r = modus_ponens(Fact("a", "implies", "b"), Fact("a", "is", "a"))
    assert r and r.subject == "a" and r.object == "b"


def test_same_subject_object_implication():
    r = modus_ponens(Fact("a", "implies", "a"), Fact("x", "is", "a"))
    assert r and r.subject == "x" and r.object == "a"
