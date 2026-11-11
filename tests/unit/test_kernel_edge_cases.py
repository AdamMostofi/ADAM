"""Red-team edge cases for the Layer 1 rules and the engine (Stage 1.1, #27)."""
from __future__ import annotations

import itertools

import pytest

from kernel.engine import InferenceEngine
from kernel.facts import Fact, Source
from kernel.foundations import (
    TRUE,
    canonical_term,
    literal_triple,
    negate_term,
    split_term,
)
from kernel.rules import BUILTIN_RULES


def triple(f):
    return (f.subject, f.predicate, f.object)


# ------------------------------------------------------------ negated terms
@pytest.mark.parametrize("term, expected", [
    ("a", "a"), ("not:a", "not:a"), ("not:not:a", "a"), ("not:not:not:a", "not:a"), ("not:", "not:"),
])
def test_canonical_term_cancels_pairs_of_negations(term, expected):
    assert canonical_term(term) == expected


def test_negating_twice_returns_the_canonical_term():
    for term in ("a", "not:a", "not:not:a"):
        assert negate_term(negate_term(term)) == canonical_term(term)


def test_bare_prefix_is_an_ordinary_term():
    assert split_term("not:") == ("not:", False)


def test_literal_triples_are_canonical():
    assert literal_triple("a") == ("a", "is", TRUE)
    assert literal_triple("not:a") == ("a", "not_is", TRUE)
    assert literal_triple("not:not:a") == ("a", "is", TRUE)


# ------------------------------------------------------------- every rule fires
FIRING_EXAMPLES = {
    "modus_ponens": [Fact("x", "is", "p"), Fact("p", "implies", "q")],
    "modus_ponens_negated": [Fact("a", "not_is", TRUE), Fact("not:a", "implies", "b")],
    "transitivity": [Fact("p", "implies", "q"), Fact("q", "implies", "r")],
    "modus_tollens": [Fact("p", "implies", "q"), Fact("x", "not_is", "q")],
    "modus_tollens_negated": [Fact("a", "implies", "not:b"), Fact("b", "is", TRUE)],
    "existential_generalization": [Fact("x", "is", "p")],
    "subtype_transitivity": [Fact("x", "is", "p"), Fact("p", "implies", "q")],
    "is_transitivity": [Fact("x", "is", "p"), Fact("p", "is", "q")],
    "universal_instantiation": [Fact("p", "all_are", "q"), Fact("x", "is", "p")],
    "universal_generalization": [Fact("arbitrary_p", "is", "q")],
    "equality_symmetry": [Fact("a", "equals", "b")],
    "disjunctive_syllogism_not_is": [Fact("a", "or", "b"), Fact("a", "not_is", TRUE)],
    "disjunctive_syllogism_is": [Fact("not:a", "or", "b"), Fact("a", "is", TRUE)],
    "de_morgan_and": [Fact("a", "not_and", "b")],
    "de_morgan_or": [Fact("a", "not_or", "b")],
    "double_negation": [Fact("a", "not_not", TRUE)],
    "conditional_proof": [Fact("c1", "assumes", "rain"), Fact("c1", "derives", "wet")],
}
for _p in ("is", "not_is", "implies", "all_are", "or", "equals"):
    FIRING_EXAMPLES[f"equality_substitution_{_p}"] = [Fact("a", "equals", "b"), Fact("a", _p, "c")]


def test_every_registered_rule_has_a_firing_example():
    assert {r.name for r in BUILTIN_RULES} == set(FIRING_EXAMPLES)


@pytest.mark.parametrize("rule", BUILTIN_RULES, ids=lambda r: r.name)
def test_every_registered_rule_fires_through_the_engine(rule):
    engine = InferenceEngine()
    engine.add_facts(FIRING_EXAMPLES[rule.name])
    engine.infer()
    fired = [step for step in engine.get_trace() if step.startswith(f"[{rule.name}]")]
    assert fired, f"{rule.name} never fired; trace: {engine.get_trace()}"


# ---------------------------------------------------------------- confidence
@pytest.mark.parametrize("rule", BUILTIN_RULES, ids=lambda r: r.name)
@pytest.mark.parametrize("confidence", [0.0, 1e-9, 0.5, 1.0])
def test_confidence_stays_between_zero_and_one(rule, confidence):
    facts = [Fact(f.subject, f.predicate, f.object, confidence=confidence) for f in FIRING_EXAMPLES[rule.name]]
    args = facts[:1] if rule.partner is None else (facts[0], facts[1])
    if rule.partner is not None and facts[0].predicate != rule.trigger:
        args = (facts[1], facts[0])
    out = rule.apply(*args)
    for r in (out if isinstance(out, list) else [out] if out else []):
        assert 0.0 <= r.confidence <= confidence
        assert r.source == Source.DEDUCED


# ------------------------------------------------------------- odd inputs
WEIRD_TERMS = ["a b", "  spaced  ", "ünïcödé", "日本", "x" * 500, "?x", "true", "exists", "not:", "arbitrary_"]


def test_rules_never_crash_on_odd_terms():
    facts = [Fact(s, p, o) for s, o in itertools.product(WEIRD_TERMS[:6], repeat=2)
             for p in ("is", "not_is", "implies", "or", "equals", "all_are")]
    by_predicate = {}
    for f in facts:
        by_predicate.setdefault(f.predicate, []).append(f)
    for rule in BUILTIN_RULES:
        for f in by_predicate.get(rule.trigger, []):
            partners = [None] if rule.partner is None else by_predicate.get(rule.partner, [])[:20]
            for g in partners:
                rule.apply(f) if g is None else rule.apply(f, g)


@pytest.mark.parametrize("term", WEIRD_TERMS)
def test_engine_handles_reserved_and_odd_terms(term):
    engine = InferenceEngine()
    engine.add_facts([Fact(term, "is", "thing"), Fact("thing", "implies", "item")])
    engine.infer()
    assert engine.query(term, "is", "item") or term == "true"


def test_self_referential_facts_produce_no_trivial_beliefs():
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "is", "a"), Fact("a", "implies", "a"), Fact("a", "equals", "a"),
                      Fact("a", "or", "a"), Fact("a", "all_are", "a"), Fact("a", "not_not", "a")])
    engine.infer()
    trivial = [k for k in engine.beliefs if k.split()[0] == k.split()[-1] and k.split()[1] in ("is", "implies", "all_are", "equals")]
    assert set(trivial) == {"a is a", "a implies a", "a all_are a", "a equals a"}  # only the given ones


def test_cycles_terminate_and_stay_small():
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "implies", "b"), Fact("b", "implies", "c"), Fact("c", "implies", "a"),
                      Fact("x", "is", "a"), Fact("a", "equals", "z"), Fact("z", "equals", "a")])
    engine.infer()
    assert len(engine.beliefs) < 60
    assert engine.prove("x", "is", "c") is not None


def test_contradiction_is_flagged_not_exploded():
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "is", TRUE), Fact("a", "not_is", TRUE), Fact("a", "implies", "b")])
    engine.infer()
    assert engine.query("a", "contradiction", TRUE)
    assert not engine.query("zzz", "is", TRUE)  # ex falso quodlibet must not happen


def test_equality_is_symmetric_and_transitive():
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "equals", "b"), Fact("b", "equals", "c")])
    engine.infer()
    assert engine.query("b", "equals", "a")
    assert engine.query("a", "equals", "c")
    assert engine.query("c", "equals", "a")
    assert not engine.query("a", "equals", "a")


def test_equality_substitutes_into_negations_and_implications():
    engine = InferenceEngine()
    engine.add_facts([Fact("morning_star", "equals", "evening_star"),
                      Fact("morning_star", "not_is", "planet_x"),
                      Fact("evening_star", "implies", "bright")])
    engine.infer()
    assert engine.query("evening_star", "not_is", "planet_x")
    assert engine.query("morning_star", "implies", "bright")


def test_modus_ponens_does_not_treat_true_as_a_class():
    engine = InferenceEngine()
    engine.add_facts([Fact("rain", "is", TRUE), Fact("true", "implies", "weird")])
    engine.infer()
    assert not engine.query("rain", "is", "weird")


def test_existential_does_not_fire_on_propositions():
    engine = InferenceEngine()
    engine.add_facts([Fact("rain", "is", TRUE)])
    engine.infer()
    assert not engine.query("exists", "is", TRUE)
