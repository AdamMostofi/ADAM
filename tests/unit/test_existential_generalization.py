"""Unit tests for existential_generalization: If a is X, then there exists X.

Purpose: Verify creating existential knowledge from specific instances.
Result: PASS
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import existential_generalization


def test_normal():
    """Tests basic existential generalization: socrates is mortal => exists is mortal. Result: PASS."""
    r = existential_generalization(Fact("socrates", "is", "mortal"))
    assert r and r.subject == "exists" and r.predicate == "is" and r.object == "mortal"


def test_wrong_predicate():
    """Tests that non-'is' predicates return None. Result: PASS."""
    assert existential_generalization(Fact("socrates", "equals", "mortal")) is None


def test_self_referential():
    """Tests existential generalization with self-referential fact. Result: PASS."""
    r = existential_generalization(Fact("a", "is", "a"))
    assert r and r.subject == "exists" and r.object == "a"


def test_confidence_preserved():
    """Tests that confidence is preserved (no decay). Result: PASS."""
    r = existential_generalization(Fact("socrates", "is", "mortal", confidence=0.7))
    assert r and r.confidence == 0.7
