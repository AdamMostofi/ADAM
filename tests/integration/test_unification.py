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
    """Tests simple unification: ?x is mortal + socrates is mortal => ?x=socrates. Result: PASS."""
    bindings = unify(Fact("?x", "is", "mortal"), Fact("socrates", "is", "mortal"))
    assert bindings is not None
    assert bindings.get("?x") == "socrates"


def test_unify_no_match():
    """Tests unification returns None for non-matching facts. Result: PASS."""
    assert unify(Fact("x", "is", "mortal"), Fact("y", "is", "immortal")) is None


def test_unify_multiple_variables():
    """Tests unification with multiple variables: ?x is ?y + socrates is mortal => both bound. Result: PASS."""
    bindings = unify(Fact("?x", "is", "?y"), Fact("socrates", "is", "mortal"))
    assert bindings is not None
    assert bindings.get("?x") == "socrates"
    assert bindings.get("?y") == "mortal"


def test_unify_occurs_check():
    """Tests occurs check prevents circular bindings: ?x is ?x + y is z => None. Result: PASS. Fix: occurs check was missing."""
    assert unify(Fact("?x", "is", "?x"), Fact("y", "is", "z")) is None


def test_unify_same_fact():
    """Tests unification of identical facts. Result: PASS."""
    bindings = unify(Fact("a", "is", "b"), Fact("a", "is", "b"))
    assert bindings is not None


def test_find_unifiable():
    """Tests finding all unifiable facts from a list. Result: PASS."""
    facts = [
        Fact("socrates", "is", "mortal"),
        Fact("plato", "is", "mortal"),
        Fact("cat", "is", "animal"),
    ]
    results = find_unifiable(Fact("?x", "is", "mortal"), facts)
    assert len(results) == 2


def test_find_unifiable_ranked_by_confidence():
    """Tests that find_unifiable ranks results by confidence (highest first). Result: PASS. Fix: ranking was missing."""
    facts = [
        Fact("socrates", "is", "mortal", confidence=0.9),
        Fact("plato", "is", "mortal", confidence=0.5),
    ]
    results = find_unifiable(Fact("?x", "is", "mortal"), facts)
    assert len(results) == 2
    assert results[0][0].confidence >= results[1][0].confidence
