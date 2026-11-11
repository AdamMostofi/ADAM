"""Forward inference, backward proof, and a reference evaluator must agree (Stage 1.1, #27).

The reference evaluator is deliberately naive: it applies every registered
rule to every pair of facts until nothing new appears. That makes it the
definition of what the Layer 1 rules derive. Then, on generated fact sets:

* prove() is sound: anything it proves is in the reference closure;
* prove() is complete: everything in the reference closure it handles is provable;
* infer() is sound: everything it derives is in the reference closure.

infer() is not yet complete when facts depend on facts derived later; that is
Stage 1.2 (#28) and is recorded in test_known_kernel_gaps.py.
"""
from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from kernel.engine import InferenceEngine
from kernel.facts import Fact
from kernel.foundations import EXISTS, TRUE, contradiction_detection
from kernel.rules import BUILTIN_RULES

PROVABLE_PREDICATES = ("is", "not_is", "implies", "all_are", "or", "equals")
CLASS_TERMS = ["a", "b", "c"]
PROP_TERMS = CLASS_TERMS + ["not:a", "not:b"]


def key(f):
    return (f.subject, f.predicate, f.object)


def reference_closure(facts: list[Fact]) -> set[tuple[str, str, str]]:
    known = {key(f): f for f in facts}
    while True:
        by_predicate: dict[str, list[Fact]] = {}
        for f in known.values():
            by_predicate.setdefault(f.predicate, []).append(f)
        new = {}
        for rule in BUILTIN_RULES:
            firsts = by_predicate.get(rule.trigger, [])
            combos = [(f,) for f in firsts] if rule.partner is None else \
                [(f, g) for f in firsts for g in by_predicate.get(rule.partner, [])]
            for args in combos:
                out = rule.apply(*args)
                for r in (out if isinstance(out, list) else [out] if out else []):
                    if key(r) not in known:
                        new[key(r)] = r
        for f in by_predicate.get("is", []) + by_predicate.get("not_is", []):
            for g in by_predicate.get("is", []) + by_predicate.get("not_is", []):
                c = contradiction_detection(f, g)
                if c and key(c) not in known:
                    new[key(c)] = c
        if not new:
            return set(known)
        known.update(new)


fact_strategy = st.one_of(
    st.builds(Fact, st.sampled_from(CLASS_TERMS), st.sampled_from(["is", "not_is"]), st.sampled_from(CLASS_TERMS)),
    st.builds(Fact, st.sampled_from(PROP_TERMS), st.sampled_from(["is", "not_is"]), st.just(TRUE)),
    st.builds(Fact, st.sampled_from(CLASS_TERMS), st.sampled_from(["implies", "all_are", "equals"]), st.sampled_from(CLASS_TERMS)),
    st.builds(Fact, st.sampled_from(PROP_TERMS), st.sampled_from(["implies", "or", "not_and", "not_or"]), st.sampled_from(PROP_TERMS)),
    st.builds(Fact, st.sampled_from(PROP_TERMS), st.just("not_not"), st.sampled_from(CLASS_TERMS + [TRUE])),
    st.builds(Fact, st.sampled_from(["arbitrary_a", "arbitrary_b"]), st.just("is"), st.sampled_from(CLASS_TERMS)),
    st.builds(Fact, st.just("ctx"), st.sampled_from(["assumes", "derives"]), st.sampled_from(CLASS_TERMS)),
)
fact_sets = st.lists(fact_strategy, min_size=1, max_size=5, unique_by=key)


def engine_with(facts):
    engine = InferenceEngine()
    engine.add_facts(facts)
    return engine


def candidate_goals(closure):
    terms = {t for s, _, o in closure for t in (s, o)} | {EXISTS, "a", "b"}
    for s in terms:
        for o in terms | {TRUE}:
            for p in PROVABLE_PREDICATES:
                if o == TRUE and (p not in ("is", "not_is") or s.startswith("not:")):
                    continue  # only canonical propositional goals
                yield (s, p, o)


SETTINGS = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@SETTINGS
@given(fact_sets)
def test_prove_is_sound(facts):
    closure = reference_closure(facts)
    engine = engine_with(facts)
    for goal in candidate_goals(closure):
        if engine.prove(*goal, max_depth=12) is not None:
            assert goal in closure, f"prove() claimed {goal} from {[key(f) for f in facts]}"


@SETTINGS
@given(fact_sets)
def test_prove_is_complete_for_what_the_rules_derive(facts):
    closure = reference_closure(facts)
    engine = engine_with(facts)
    for goal in sorted(closure):
        if goal[1] in PROVABLE_PREDICATES:
            assert engine.prove(*goal, max_depth=12) is not None, \
                f"prove() missed {goal} from {[key(f) for f in facts]}"


@SETTINGS
@given(fact_sets)
def test_infer_is_sound(facts):
    closure = reference_closure(facts)
    engine = engine_with(facts)
    engine.infer()
    derived = {key(b.fact) for b in engine.beliefs.values()}
    assert derived <= closure, f"infer() derived {derived - closure} from {[key(f) for f in facts]}"


def test_prove_no_longer_uses_a_reflexive_axiom():
    """The old prove() proved "rain is wet" from "rain implies wet"; forward inference never could."""
    engine = engine_with([Fact("rain", "implies", "wet")])
    assert engine.prove("rain", "is", "wet") is None
    engine = engine_with([Fact("rain", "implies", "wet"), Fact("rain", "is", TRUE)])
    assert engine.prove("wet", "is", TRUE) is not None


def test_prove_follows_a_propositional_chain():
    engine = engine_with([
        Fact("sunny", "not_and", "rainy"), Fact("sunny", "is", TRUE),
        Fact("not:rainy", "implies", "dry"),
    ])
    proof = engine.prove("dry", "is", TRUE)
    assert proof is not None and any("de_morgan_and" in step for step in proof)
