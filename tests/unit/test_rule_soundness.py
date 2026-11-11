"""Exhaustive soundness checks for every Layer 1 rule (Stage 1.1, #27).

A rule is sound if, in every model where its premises are true, its
conclusion is true too. Rather than trusting hand-picked examples, these tests
feed each rule every combination of premises over a small vocabulary and check
the conclusion in every model:

* Propositions: atoms a, b, c and their negated terms, under all 8 truth
  assignments.
* Classes (Stage 1.3, #29): individuals x, y as elements of {1, 2} and
  classes p, q, r as non-empty subsets of it, under all 108 models.
  instance_of is membership, subclass_of and implies are subset, and an
  ambiguous "is" means membership for an individual and subset for a class.
  Rules can't tell the two readings of "is" apart, so passing means they are
  sound under both.
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
CLASS_ONLY = ("subclass_transitivity", "inheritance", "exclusion", "existential_generalization",
              "universal_generalization", "conditional_proof")
PROP_RULES = [r for r in BUILTIN_RULES if not r.name.startswith(CLASS_ONLY)]


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


# ------------------------------------------------------------------ classes
INDIVIDUALS = ("x", "y")
CLASSES = ("p", "q", "r")
NONEMPTY_SUBSETS = [frozenset(s) for s in ({1}, {2}, {1, 2})]
CLASS_MODELS = [
    {**dict(zip(INDIVIDUALS, elements)), **dict(zip(CLASSES, sets))}
    for elements in itertools.product((1, 2), repeat=len(INDIVIDUALS))
    for sets in itertools.product(NONEMPTY_SUBSETS, repeat=len(CLASSES))
]
CLASS_RULES = [r for r in BUILTIN_RULES if r.name not in {"universal_generalization", "conditional_proof"}]


def class_facts():
    """Every well-typed class fact over the vocabulary."""
    facts = []
    for i, c in itertools.product(INDIVIDUALS, CLASSES):
        facts += [Fact(i, p, c) for p in ("instance_of", "not_instance_of", "is", "not_is")]
    for c, d in itertools.product(CLASSES, repeat=2):
        facts += [Fact(c, p, d) for p in ("subclass_of", "implies", "is", "not_is", "equals")]
    facts += [Fact(i, "equals", j) for i, j in itertools.product(INDIVIDUALS, repeat=2)]
    return facts


def class_holds(f, model):
    s, p, o = f.subject, f.predicate, f.object
    if s == EXISTS and p == "instance_of":
        return bool(model[o])
    a, b = model[s], model[o]
    individual = s in INDIVIDUALS
    if p == "equals":
        return a == b
    if p in ("instance_of", "not_instance_of"):
        assert individual, f"ill-typed: {f}"
        return (a in b) == (p == "instance_of")
    if p in ("subclass_of", "implies"):
        return a <= b
    if p in ("is", "not_is"):
        holds = (a in b) if individual else (a <= b)
        return holds == (p == "is")
    raise AssertionError(f"no class meaning for {f}")


def test_every_class_rule_is_sound_under_both_readings_of_is():
    checked, failures = 0, []
    for rule, premises, conclusion in applications(CLASS_RULES, class_facts()):
        checked += 1
        satisfying = [m for m in CLASS_MODELS if all(class_holds(p, m) for p in premises)]
        if conclusion.predicate == "contradiction":
            if satisfying:
                failures.append((rule.name, premises, "flagged a satisfiable pair"))
            continue
        for model in satisfying:
            if not class_holds(conclusion, model):
                failures.append((rule.name, [str(p) for p in premises], str(conclusion)))
                break
    assert checked > 500, f"too few applications checked ({checked})"
    assert not failures, failures[:5]


def test_no_rule_chains_membership_through_a_class_of_classes():
    """rex is a dog and dog is a species, but rex is not a species."""
    for premises in ([Fact("rex", "instance_of", "dog"), Fact("dog", "instance_of", "species")],
                     [Fact("rex", "is", "dog"), Fact("dog", "is", "species")]):
        for a, b in itertools.permutations(premises):
            for rule in BUILTIN_RULES:
                if rule.partner is None:
                    continue
                for out in outputs(rule, (a, b)):
                    assert (out.subject, out.object) != ("rex", "species"), (rule.name, str(out))


# --------------------------------------------------------------- non-truth-functional
def test_universal_generalization_needs_the_arbitrary_marker():
    rule = next(r for r in BUILTIN_RULES if r.name == "universal_generalization")
    assert rule.apply(Fact("socrates", "instance_of", "mortal")) is None
    out = rule.apply(Fact("arbitrary_man", "instance_of", "mortal"))
    assert triple(out) == ("man", "subclass_of", "mortal")


def test_conditional_proof_needs_a_shared_context():
    rule = next(r for r in BUILTIN_RULES if r.name == "conditional_proof")
    assert rule.apply(Fact("c1", "assumes", "rain"), Fact("c2", "derives", "wet")) is None
    assert triple(rule.apply(Fact("c1", "assumes", "rain"), Fact("c1", "derives", "wet"))) == ("rain", "implies", "wet")
