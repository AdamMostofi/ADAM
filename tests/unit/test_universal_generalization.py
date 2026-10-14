"""Unit tests for universal_generalization: If arbitrary_c is X, then all_c are X.

Purpose: Verify generalization from arbitrary instances to universal rules.
Result: PASS
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import universal_generalization


def test_normal():
    r = universal_generalization(Fact("arbitrary_c", "is", "mortal"))
    assert r and r.subject == "all_c" and r.predicate == "all_are" and r.object == "mortal"


def test_wrong_prefix():
    assert universal_generalization(Fact("c", "is", "mortal")) is None


def test_wrong_predicate():
    assert universal_generalization(Fact("arbitrary_c", "equals", "mortal")) is None


def test_confidence_decay():
    r = universal_generalization(Fact("arbitrary_c", "is", "mortal", confidence=0.9))
    assert r and r.confidence < 0.9
