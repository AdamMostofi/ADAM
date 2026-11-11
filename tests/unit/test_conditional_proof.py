"""Conditional proof: assuming P and deriving Q in the same context gives P implies Q.

Stage 1.1 (#27) fix: the rule used to pair any assumption with any derivation,
so "moon assumes x" and "tax derives banana" gave "moon implies banana".
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact
from kernel.foundations import conditional_proof


def test_same_context_gives_implication():
    r = conditional_proof(Fact("c1", "assumes", "rain"), Fact("c1", "derives", "wet"))
    assert (r.subject, r.predicate, r.object) == ("rain", "implies", "wet")


def test_unrelated_contexts_give_nothing():
    assert conditional_proof(Fact("moon", "assumes", "x"), Fact("tax", "derives", "banana")) is None


def test_deriving_the_assumption_itself_gives_nothing():
    assert conditional_proof(Fact("c1", "assumes", "rain"), Fact("c1", "derives", "rain")) is None


def test_wrong_predicates():
    assert conditional_proof(Fact("p", "is", "p"), Fact("q", "is", "q")) is None


def test_confidence_decay():
    r = conditional_proof(Fact("c1", "assumes", "p", confidence=0.5), Fact("c1", "derives", "q", confidence=0.5))
    assert r and r.confidence < 0.25
