"""Beliefs depend on the facts, not the order they arrive in (Stage 1.2, #28).

DR2.1: order independence is a tested invariant. For generated fact sets, the
engine must reach the same beliefs, with the same confidence and evidence,
whether the facts arrive in one batch, one at a time, in any permutation, or
in chunks with inference in between. Retracting must give the same state as
never having added the fact.
"""
from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from kernel.engine import InferenceEngine
from kernel.facts import Fact, Source
from kernel.foundations import canonical_fact
from kernel.rules import Rule
from learning.skill_compiler import Skill, skill_to_rule
from tests.integration.test_prove_agreement import fact_sets, reference_closure

SETTINGS = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def state(engine: InferenceEngine) -> dict:
    return {k: (round(b.confidence, 9), b.evidence, b.given) for k, b in engine.beliefs.items()}


def batch(facts):
    engine = InferenceEngine()
    engine.add_facts(facts)
    engine.infer()
    return engine


def in_chunks(facts, sizes):
    engine = InferenceEngine()
    i = 0
    for size in sizes:
        engine.add_facts(facts[i:i + size])
        engine.infer()
        i += size
    engine.add_facts(facts[i:])
    engine.infer()
    return engine


confident_fact_sets = fact_sets.flatmap(lambda facts: st.tuples(*[
    st.sampled_from([0.5, 0.8, 1.0]).map(lambda c, f=f: Fact(f.subject, f.predicate, f.object, confidence=c))
    for f in facts
]).map(list))


@SETTINGS
@given(confident_fact_sets, st.data())
def test_any_arrival_order_gives_the_same_beliefs(facts, data):
    expected = state(batch(facts))
    one_at_a_time = in_chunks(facts, [1] * len(facts))
    assert state(one_at_a_time) == expected
    shuffled = data.draw(st.permutations(facts))
    assert state(batch(shuffled)) == expected
    sizes = data.draw(st.lists(st.integers(1, 3), max_size=4))
    assert state(in_chunks(shuffled, sizes)) == expected


@SETTINGS
@given(fact_sets)
def test_infer_reaches_exactly_the_reference_closure(facts):
    engine = batch(facts)
    assert engine.saturated
    assert set(engine.beliefs) == reference_closure(facts)


@SETTINGS
@given(confident_fact_sets, st.data())
def test_retract_gives_the_state_without_the_fact(facts, data):
    gone = data.draw(st.sampled_from(facts))
    engine = in_chunks(facts, [1] * len(facts))
    engine.retract(gone)
    # Retracting a statement removes it however it was written ("a is true" = "not:a not_is true").
    rest = [f for f in facts if str(canonical_fact(f)) != str(canonical_fact(gone))]
    assert state(engine) == state(batch(rest))


# --- the cases from the issue


def test_issue_cases_derive_their_conclusion_one_at_a_time():
    cases = [
        ([Fact("fire", "implies", "hot"), Fact("x", "instance_of", "fire")], ("x", "instance_of", "hot")),
        ([Fact("bird", "all_are", "flier"), Fact("tweety", "instance_of", "bird")], ("tweety", "instance_of", "flier")),
        # Written with "is" in #28; since Stage 1.3 two ambiguous "is" facts don't chain.
        ([Fact("a", "subclass_of", "b"), Fact("b", "subclass_of", "c")], ("a", "subclass_of", "c")),
        ([Fact("b", "subclass_of", "c"), Fact("a", "instance_of", "b")], ("a", "instance_of", "c")),
    ]
    for facts, goal in cases:
        assert in_chunks(facts, [1, 1]).query(*goal), goal
        assert batch(facts).query(*goal), goal


def test_different_facts_never_share_a_belief():
    engine = InferenceEngine()
    engine.add_facts([Fact("new york", "is", "city"), Fact("new", "york is", "city")])
    assert len(engine.beliefs) == 2
    assert engine.query("new york", "is", "city") and engine.query("new", "york is", "city")


# --- layer 2 rules


def mortal_skill(premises):
    return skill_to_rule(Skill(name="mortality", domain="test", premises=premises,
                               conclusion={"subject": "?x", "predicate": "is", "object": "mortal"},
                               confidence=0.9))


def test_add_rule_applies_to_beliefs_already_known():
    rule = mortal_skill([{"subject": "?x", "predicate": "is", "object": "man"}])
    before = InferenceEngine()
    before.add_rule(rule)
    before.add_facts([Fact("socrates", "is", "man")])
    before.infer()
    after = batch([Fact("socrates", "is", "man")])
    after.add_rule(rule)
    after.infer()
    assert after.query("socrates", "is", "mortal")
    assert state(after) == state(before)


def test_two_premise_rule_added_late_sees_both_premises():
    rule = mortal_skill([{"subject": "?x", "predicate": "is", "object": "man"},
                         {"subject": "?x", "predicate": "lives_in", "object": "athens"}])
    engine = batch([Fact("socrates", "is", "man"), Fact("socrates", "lives_in", "athens")])
    engine.add_rule(rule)
    engine.infer()
    assert engine.query("socrates", "is", "mortal")


def test_a_single_premise_skill_does_not_crash_the_engine():
    engine = InferenceEngine()
    engine.add_rule(mortal_skill([{"subject": "?x", "predicate": "is", "object": "man"}]))
    engine.add_fact(Fact("plato", "is", "man"))
    engine.infer()
    assert engine.query("plato", "is", "mortal")


def test_a_skill_conclusion_is_removed_with_its_premise():
    """Skill outputs carry Source.LEARNED; they must still go when their premise is retracted."""
    engine = InferenceEngine()
    engine.add_rule(mortal_skill([{"subject": "?x", "predicate": "is", "object": "man"}]))
    engine.add_fact(Fact("plato", "is", "man"))
    engine.infer()
    engine.retract(Fact("plato", "is", "man"))
    assert not engine.query("plato", "is", "mortal")


def test_a_custom_rule_without_shared_terms_still_fires():
    """Layer 2 rules are matched against every fact of their partner predicate."""
    def pair(a, b):
        if a.predicate == "likes" and b.predicate == "hates":
            return Fact(a.subject, "is", "conflicted")
        return None
    engine = InferenceEngine()
    engine.add_rule(Rule("conflict", "likes", "hates", pair))
    engine.add_facts([Fact("ann", "likes", "tea"), Fact("bob", "hates", "coffee")])
    engine.infer()
    assert engine.query("ann", "is", "conflicted")


# --- budget


def test_the_budget_is_reported_and_work_resumes():
    engine = InferenceEngine()
    engine.add_facts([Fact(f"n{i}", "is", f"n{i + 1}") for i in range(20)])
    engine.infer(max_iterations=5)
    assert engine.last_run["iterations"] == 5 and not engine.last_run["saturated"]
    assert engine.last_run["rule_applications"] > 0
    while not engine.saturated:
        engine.infer(max_iterations=5)
    assert state(engine) == state(batch([Fact(f"n{i}", "is", f"n{i + 1}") for i in range(20)]))


def test_giving_a_derived_fact_marks_it_given():
    engine = batch([Fact("x", "is", "a"), Fact("a", "implies", "b")])
    assert not engine.beliefs[("x", "is", "b")].given
    engine.add_fact(Fact("x", "is", "b", source=Source.LEARNED))
    assert engine.beliefs[("x", "is", "b")].given
    engine.retract(Fact("a", "implies", "b"))
    assert engine.query("x", "is", "b")


# --- regressions found by the deep property run


def test_the_same_statement_given_twice_keeps_the_higher_confidence_in_any_order():
    first = [Fact("a", "is", "true", confidence=0.5), Fact("not:a", "not_is", "true", confidence=0.8)]
    for facts in (first, first[::-1]):
        assert abs(batch(facts).query("a", "is", "true")[0].confidence - 0.8) < 1e-9


def test_retract_restores_the_given_confidence_not_a_derived_one():
    facts = [Fact("b", "is", "a", confidence=0.5), Fact("b", "not_not", "a", confidence=0.8)]
    engine = batch(facts)
    assert abs(engine.query("b", "is", "a")[0].confidence - 0.8) < 1e-9  # raised by double negation
    engine.retract(Fact("b", "not_not", "a"))
    assert abs(engine.query("b", "is", "a")[0].confidence - 0.5) < 1e-9
