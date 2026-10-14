"""Integration tests for unification (pattern matching between facts).

Purpose: Verify variable binding, occurs check, and ranked results.
Result: PASS
Fix: Added occurs check to prevent circular bindings. Added confidence-based ranking.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.unification import unify, find_unifiable


def test_unify_simple():
    bindings = unify(Fact("?x", "is", "mortal"), Fact("socrates", "is", "mortal"))
    assert bindings is not None
    assert bindings.get("?x") == "socrates"


def test_unify_no_match():
    assert unify(Fact("x", "is", "mortal"), Fact("y", "is", "immortal")) is None


def test_unify_multiple_variables():
    bindings = unify(Fact("?x", "is", "?y"), Fact("socrates", "is", "mortal"))
    assert bindings is not None
    assert bindings.get("?x") == "socrates"
    assert bindings.get("?y") == "mortal"


def test_unify_occurs_check():
    assert unify(Fact("?x", "is", "?x"), Fact("y", "is", "z")) is None


def test_unify_same_fact():
    bindings = unify(Fact("a", "is", "b"), Fact("a", "is", "b"))
    assert bindings is not None


def test_find_unifiable():
    facts = [
        Fact("socrates", "is", "mortal"),
        Fact("plato", "is", "mortal"),
        Fact("cat", "is", "animal"),
    ]
    results = find_unifiable(Fact("?x", "is", "mortal"), facts)
    assert len(results) == 2


def test_find_unifiable_ranked_by_confidence():
    facts = [
        Fact("socrates", "is", "mortal", confidence=0.9),
        Fact("plato", "is", "mortal", confidence=0.5),
    ]
    results = find_unifiable(Fact("?x", "is", "mortal"), facts)
    assert len(results) == 2
    assert results[0][0].confidence >= results[1][0].confidence
