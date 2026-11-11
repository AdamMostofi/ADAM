"""De Morgan's laws.

not(A and B) is (not A) or (not B): neither negation follows on its own.
not(A or B) is (not A) and (not B): both negations follow.

Stage 1.1 (#27) fix: de_morgan_and used to assert both negations, which is
unsound (not(rain and cold) does not mean it is neither raining nor cold).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact
from kernel.foundations import de_morgan_and, de_morgan_or, disjunctive_syllogism


def triple(f):
    return (f.subject, f.predicate, f.object)


def test_not_and_gives_a_disjunction_of_negations_not_both_negations():
    results = de_morgan_and(Fact("rain", "not_and", "cold"))
    assert [triple(r) for r in results] == [("not:rain", "or", "not:cold")]


def test_not_and_with_one_known_conjunct_gives_the_other_negation():
    disjunction = de_morgan_and(Fact("rain", "not_and", "cold"))[0]
    result = disjunctive_syllogism(disjunction, Fact("rain", "is", "true"))
    assert triple(result) == ("cold", "not_is", "true")


def test_not_and_of_a_term_with_itself_negates_it():
    assert [triple(r) for r in de_morgan_and(Fact("a", "not_and", "a"))] == [("a", "not_is", "true")]


def test_not_and_cancels_double_negation_in_terms():
    results = de_morgan_and(Fact("not:a", "not_and", "b"))
    assert [triple(r) for r in results] == [("a", "or", "not:b")]


def test_not_or_gives_both_negations():
    results = de_morgan_or(Fact("a", "not_or", "b"))
    assert sorted(triple(r) for r in results) == [("a", "not_is", "true"), ("b", "not_is", "true")]


def test_not_or_with_a_negated_term_gives_its_positive_form():
    results = de_morgan_or(Fact("not:a", "not_or", "b"))
    assert sorted(triple(r) for r in results) == [("a", "is", "true"), ("b", "not_is", "true")]


def test_not_or_of_a_term_with_itself_gives_one_fact():
    assert len(de_morgan_or(Fact("a", "not_or", "a"))) == 1


def test_wrong_predicate_returns_empty():
    assert de_morgan_and(Fact("a", "is", "b")) == []
    assert de_morgan_or(Fact("a", "is", "b")) == []


def test_confidence_is_preserved():
    assert de_morgan_and(Fact("a", "not_and", "b", confidence=0.4))[0].confidence == 0.4
