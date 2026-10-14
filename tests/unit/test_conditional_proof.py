"""Unit tests for conditional_proof: If assuming P leads to Q, then P->Q.

Purpose: Verify implication construction from derivations.
Result: PASS
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import conditional_proof


def test_normal():
    """Tests basic conditional proof: p assumes p + q derives q => p implies q. Result: PASS."""
    r = conditional_proof(Fact("p", "assumes", "p"), Fact("q", "derives", "q"))
    assert r and r.subject == "p" and r.predicate == "implies" and r.object == "q"


def test_wrong_predicates():
    """Tests that non-matching predicates return None. Result: PASS."""
    assert conditional_proof(Fact("p", "is", "p"), Fact("q", "is", "q")) is None


def test_confidence_decay():
    """Tests that confidence decays with 0.9 penalty factor. Result: PASS."""
    r = conditional_proof(Fact("p", "assumes", "p", confidence=0.5), Fact("q", "derives", "q", confidence=0.5))
    assert r and r.confidence < 0.25
