"""Disjunctive syllogism: A or B with not-A gives B (and with not-B gives A).

Stage 1.1 (#27) fix: the rule used to ignore what was negated, so
"a or b" with "a not_is blue" gave "b is true".
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact
from kernel.foundations import disjunctive_syllogism


def triple(f):
    return (f.subject, f.predicate, f.object)


def test_not_a_gives_b():
    r = disjunctive_syllogism(Fact("sunny", "or", "rainy"), Fact("sunny", "not_is", "true"))
    assert triple(r) == ("rainy", "is", "true")


def test_not_b_gives_a():
    r = disjunctive_syllogism(Fact("sunny", "or", "rainy"), Fact("rainy", "not_is", "true"))
    assert triple(r) == ("sunny", "is", "true")


def test_negating_something_else_gives_nothing():
    assert disjunctive_syllogism(Fact("a", "or", "b"), Fact("a", "not_is", "blue")) is None


def test_unrelated_negation_gives_nothing():
    assert disjunctive_syllogism(Fact("a", "or", "b"), Fact("c", "not_is", "true")) is None


def test_negated_disjunct_is_ruled_out_by_its_positive_fact():
    r = disjunctive_syllogism(Fact("not:a", "or", "b"), Fact("a", "is", "true"))
    assert triple(r) == ("b", "is", "true")


def test_concluding_a_negated_disjunct_gives_the_canonical_negation():
    r = disjunctive_syllogism(Fact("a", "or", "not:b"), Fact("a", "not_is", "true"))
    assert triple(r) == ("b", "not_is", "true")


def test_a_positive_fact_does_not_rule_out_a_positive_disjunct():
    assert disjunctive_syllogism(Fact("a", "or", "b"), Fact("a", "is", "true")) is None


def test_confidence_multiplicative():
    r = disjunctive_syllogism(Fact("a", "or", "b", confidence=0.5), Fact("a", "not_is", "true", confidence=0.5))
    assert abs(r.confidence - 0.25) < 1e-9
