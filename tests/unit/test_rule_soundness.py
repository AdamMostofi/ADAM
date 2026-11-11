"""Exhaustive soundness checks for every Layer 1 rule (Stage 1.1, #27).

A rule is sound if, in every model where its premises are true, its
conclusion is true too. Rather than trusting hand-picked examples, these tests
feed each rule every combination of premises over a small vocabulary and check
the conclusion in every model:

* Propositions: atoms a, b, c and their negated terms, under all 8 truth
  assignments.
* Classes, subclass reading: terms p, q, r as non-empty subsets of {1, 2},
  under all 27 models. ("is" then means subset; see Stage 1.3 for membership.)
* Classes, membership reading: individuals x, y and classes P, Q, R, for the
  rules that stay sound under it.
"""
from __future__ import annotations

import itertools

import pytest

from kernel.facts import Fact
from kernel.foundations import EXISTS, TRUE, split_term
from kernel.rules import BUILTIN_RULES


def triple(f):
    return (f.subject, f.predicate, f.object)


def outputs(rule, args):
    result = rule.apply(*args)
    if result is None:
        return []
    return result if isinstance(result, list) else [result]


def applications(rules, facts):
    """Every (rule, premises, conclusion) the rules give on `facts`."""
    by_predicate: dict[str, list[Fact]] = {}
    for f in facts:
        by_predicate.setdefault(f.predicate, []).append(f)
    for rule in rules:
        firsts = by_predicate.get(rule.trigger, [])
        if rule.partner is None:
            combos = [(f,) for f in firsts]
        else:
            combos = [(f, g) for f in firsts for g in by_predicate.get(rule.partner, [])]
        for args in combos:
            for out in outputs(rule, args):
                yield rule, args, out


# ------------------------------------------------------------------ propositions
ATOMS = ("a", "b", "c")
TERMS = ATOMS + ("not:a", "not:b", "not:not:a")
PROP_RULES = [r for r in BUILTIN_RULES if r.name not in {
    "existential_generalization", "universal_generalization", "conditional_proof",
    "is_transitivity", "subtype_transitivity", "universal_instantiation"}]


def prop_facts():
    facts = []
    for t in TERMS:
        facts += [Fact(t, "is", TRUE), Fact(t, "not_is", TRUE), Fact(t, "not_not", TRUE)]
    for x, y in itertools.product(TERMS, repeat=2):
        for predicate in ("implies", "or", "not_and", "not_or", "equals"):
            facts.append(Fact(x, predicate, y))
    return facts


def term_value(term, model):
    base, negated = split_term(term)
    return (not model[base]) if negated else model[base]


def prop_holds(f, model):
    s, p, o = f.subject, f.predicate, f.object
    if p in ("is", "not_is", "not_not"):
        assert o == TRUE, f"not a proposition: {f}"
        value = term_value(s, model)
        return (not value) if p == "not_is" else value
    a, b = term_value(s, model), term_value(o, model)
    return {"implies": (not a) or b, "or": a or b, "not_and": not (a and b),
            "not_or": not (a or b), "equals": a == b}[p]


PROP_MODELS = [dict(zip(ATOMS, values)) for values in itertools.product([False, True], repeat=len(ATOMS))]


def test_every_propositional_rule_is_sound_in_every_model():
    checked, failures = 0, []
    for rule, premises, conclusion in applications(PROP_RULES, prop_facts()):
        checked += 1
        satisfying = [m for m in PROP_MODELS if all(prop_holds(p, m) for p in premises)]
        if conclusion.predicate == "contradiction":
            if satisfying:
                failures.append((rule.name, premises, conclusion, "flagged a satisfiable pair"))
            continue
        for model in satisfying:
            if not prop_holds(conclusion, model):
                failures.append((rule.name, [str(p) for p in premises], str(conclusion), model))
                break
    assert checked > 1000, f"too few applications checked ({checked})"
    assert not failures, failures[:5]


def test_the_old_de_morgan_and_would_have_failed_this_check():
    """Guard the guard: the check above must catch the rule this stage fixed."""
    premise = Fact("rain", "not_and", "cold")
    old_conclusions = [Fact("rain", "not_is", TRUE), Fact("cold", "not_is", TRUE)]
    model = {"rain": True, "cold": False}
    term_value_model = {**model}
    holds = lambda f: prop_holds(f, term_value_model)  # noqa: E731
    assert holds(premise) and not all(holds(c) for c in old_conclusions)


# ---------------------------------------------------- classes: subclass reading
CLASSES = ("p", "q", "r")
NONEMPTY_SUBSETS = [frozenset(s) for s in ({1}, {2}, {1, 2})]
SET_MODELS = [dict(zip(CLASSES, sets)) for sets in itertools.product(NONEMPTY_SUBSETS, repeat=len(CLASSES))]
CLASS_RULES = [r for r in BUILTIN_RULES if r.name not in {"universal_generalization", "conditional_proof"}]


def class_facts():
    facts = []
    for x, y in itertools.product(CLASSES, repeat=2):
        for predicate in ("is", "not_is", "implies", "all_are", "equals"):
            facts.append(Fact(x, predicate, y))
    return facts


def set_holds(f, model):
    s, p, o = f.subject, f.predicate, f.object
    if s == EXISTS and p == "is":
        return bool(model[o])
    a, b = model[s], model[o]
    if p in ("is", "implies", "all_are"):
        return a <= b
    if p == "not_is":
        return not a <= b
    if p == "equals":
        return a == b
    raise AssertionError(f"no class meaning for {f}")


def test_every_class_rule_is_sound_under_the_subclass_reading():
    checked, failures = 0, []
    for rule, premises, conclusion in applications(CLASS_RULES, class_facts()):
        checked += 1
        satisfying = [m for m in SET_MODELS if all(set_holds(p, m) for p in premises)]
        if conclusion.predicate == "contradiction":
            if satisfying:
                failures.append((rule.name, premises, "flagged a satisfiable pair"))
            continue
        for model in satisfying:
            if not set_holds(conclusion, model):
                failures.append((rule.name, [str(p) for p in premises], str(conclusion)))
                break
    assert checked > 200, f"too few applications checked ({checked})"
    assert not failures, failures[:5]


# -------------------------------------------------- classes: membership reading
INDIVIDUALS = ("x", "y")
MEMBERSHIP_RULES = [r for r in BUILTIN_RULES if r.name in {
    "modus_ponens", "modus_tollens", "universal_instantiation", "transitivity", "existential_generalization"}]


def membership_facts():
    facts = [Fact(i, p, c) for i in INDIVIDUALS for c in CLASSES for p in ("is", "not_is")]
    facts += [Fact(c, p, d) for c, d in itertools.product(CLASSES, repeat=2) for p in ("implies", "all_are")]
    return facts


def membership_holds(f, classes):
    s, p, o = f.subject, f.predicate, f.object
    if s == EXISTS:
        return bool(classes[o])
    if p in ("implies", "all_are"):
        return classes[s] <= classes[o]
    if p == "is":
        return s in classes[o]
    if p == "not_is":
        return s not in classes[o]
    raise AssertionError(f"no membership meaning for {f}")


def test_rules_that_stay_sound_when_is_means_membership():
    universe = set(INDIVIDUALS)
    subsets = [frozenset(c) for n in range(len(universe) + 1) for c in itertools.combinations(sorted(universe), n)]
    models = [dict(zip(CLASSES, sets)) for sets in itertools.product(subsets, repeat=len(CLASSES))]
    failures = []
    for rule, premises, conclusion in applications(MEMBERSHIP_RULES, membership_facts()):
        if conclusion.predicate == "contradiction":
            continue
        for model in models:
            if all(membership_holds(p, model) for p in premises) and not membership_holds(conclusion, model):
                failures.append((rule.name, [str(p) for p in premises], str(conclusion)))
                break
    assert not failures, failures[:5]


@pytest.mark.parametrize("rule_name", ["is_transitivity"])
@pytest.mark.xfail(strict=True, reason="Stage 1.3 (#29): 'is' mixes membership and subclass")
def test_membership_reading_breaks_is_transitivity(rule_name):
    rule = next(r for r in BUILTIN_RULES if r.name == rule_name)
    conclusion = rule.apply(Fact("rex", "is", "dog"), Fact("dog", "is", "species"))
    assert conclusion is None, "rex is a dog and dog is a species, but rex is not a species"


# --------------------------------------------------------------- non-truth-functional
def test_universal_generalization_needs_the_arbitrary_marker():
    rule = next(r for r in BUILTIN_RULES if r.name == "universal_generalization")
    assert rule.apply(Fact("socrates", "is", "mortal")) is None
    out = rule.apply(Fact("arbitrary_man", "is", "mortal"))
    assert triple(out) == ("man", "all_are", "mortal")


def test_conditional_proof_needs_a_shared_context():
    rule = next(r for r in BUILTIN_RULES if r.name == "conditional_proof")
    assert rule.apply(Fact("c1", "assumes", "rain"), Fact("c2", "derives", "wet")) is None
    assert triple(rule.apply(Fact("c1", "assumes", "rain"), Fact("c1", "derives", "wet"))) == ("rain", "implies", "wet")
