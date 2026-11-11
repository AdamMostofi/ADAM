"""Class rules after splitting instance_of from subclass_of (Stage 1.3, #29).

Replaces the tests for is_transitivity, subtype_transitivity and
universal_instantiation, which assumed one "is" for both relations.
"""
from __future__ import annotations

import pytest

from kernel.engine import InferenceEngine
from kernel.facts import Fact
from kernel.foundations import (
    TRUE, canonical_fact, exclusion, existential_generalization, inheritance,
    is_ambiguous, subclass_transitivity, universal_generalization,
)


def engine_with(*triples):
    engine = InferenceEngine()
    engine.add_facts([Fact(*t) for t in triples])
    engine.infer()
    return engine


# --- acceptance criteria of #29


def test_membership_does_not_chain_through_a_class_of_classes():
    engine = engine_with(("rex", "instance_of", "dog"), ("dog", "instance_of", "species"))
    assert not engine.query("rex", "instance_of", "species")


def test_subclass_is_transitive():
    engine = engine_with(("dog", "subclass_of", "mammal"), ("mammal", "subclass_of", "animal"))
    assert engine.query("dog", "subclass_of", "animal")


def test_members_inherit_superclasses():
    engine = engine_with(("rex", "instance_of", "dog"), ("dog", "subclass_of", "mammal"))
    assert engine.query("rex", "instance_of", "mammal")


def test_inheritance_runs_down_a_whole_hierarchy():
    engine = engine_with(("tweety", "instance_of", "penguin"), ("penguin", "subclass_of", "bird"),
                         ("bird", "subclass_of", "animal"))
    assert engine.query("tweety", "instance_of", "animal")
    assert engine.query("penguin", "subclass_of", "animal")


# --- the rules on their own


def test_subclass_transitivity_accepts_implies_as_subset():
    r = subclass_transitivity(Fact("dog", "subclass_of", "mammal"), Fact("mammal", "implies", "warm_blooded"))
    assert str(r) == "dog subclass_of warm_blooded"
    r = subclass_transitivity(Fact("dog", "implies", "mammal"), Fact("mammal", "subclass_of", "animal"))
    assert str(r) == "dog subclass_of animal"


def test_two_implies_are_left_to_transitivity():
    assert subclass_transitivity(Fact("a", "implies", "b"), Fact("b", "implies", "c")) is None


def test_subclass_transitivity_ignores_unlinked_and_reflexive():
    assert subclass_transitivity(Fact("a", "subclass_of", "b"), Fact("c", "subclass_of", "d")) is None
    assert subclass_transitivity(Fact("a", "subclass_of", "b"), Fact("b", "subclass_of", "a")) is None


def test_instance_of_never_chains_with_instance_of():
    assert inheritance(Fact("dog", "instance_of", "species"), Fact("rex", "instance_of", "dog")) is None


def test_inheritance_keeps_an_ambiguous_is_ambiguous():
    # rex is dog: a member or a subclass of dog. Either way it is then one of mammal.
    r = inheritance(Fact("dog", "subclass_of", "mammal"), Fact("rex", "is", "dog"))
    assert str(r) == "rex is mammal"


def test_inheritance_through_a_class_implication():
    r = inheritance(Fact("man", "implies", "mortal"), Fact("socrates", "instance_of", "man"))
    assert str(r) == "socrates instance_of mortal"


def test_exclusion_runs_non_membership_back_up():
    r = exclusion(Fact("cat", "subclass_of", "mammal"), Fact("rock", "not_instance_of", "mammal"))
    assert str(r) == "rock not_instance_of cat"
    assert r.confidence == pytest.approx(0.9)


def test_existential_generalization_gives_membership():
    assert str(existential_generalization(Fact("rex", "instance_of", "dog"))) == "exists instance_of dog"
    assert str(existential_generalization(Fact("rex", "is", "dog"))) == "exists instance_of dog"
    assert existential_generalization(Fact("dog", "subclass_of", "mammal")) is None
    assert existential_generalization(Fact("rain", "is", TRUE)) is None


def test_universal_generalization_gives_a_subclass():
    r = universal_generalization(Fact("arbitrary_man", "instance_of", "mortal"))
    assert str(r) == "man subclass_of mortal"


def test_propositional_rules_ignore_classes():
    engine = engine_with(("x", "instance_of", "fire"), ("fire", "implies", "hot"))
    assert engine.query("x", "instance_of", "hot")
    assert not engine.query("x", "is", "hot") and not engine.query("hot", "is", TRUE)


# --- canonical forms


def test_all_are_is_written_subclass_of():
    assert str(canonical_fact(Fact("bird", "all_are", "flier"))) == "bird subclass_of flier"
    engine = engine_with(("bird", "all_are", "flier"), ("tweety", "instance_of", "bird"))
    assert engine.query("tweety", "instance_of", "flier")


def test_an_arbitrary_member_is_read_as_an_instance():
    assert str(canonical_fact(Fact("arbitrary_man", "is", "mortal"))) == "arbitrary_man instance_of mortal"
    assert str(canonical_fact(Fact("arbitrary_man", "not_is", "winged"))) == "arbitrary_man not_instance_of winged"
    engine = engine_with(("arbitrary_man", "is", "mortal"))
    assert engine.query("man", "subclass_of", "mortal")


def test_propositions_are_not_classes():
    assert not is_ambiguous(Fact("rain", "is", TRUE))
    assert is_ambiguous(Fact("rex", "is", "dog"))
    assert is_ambiguous(Fact("rex", "not_is", "cat"))
    assert not is_ambiguous(Fact("rex", "instance_of", "dog"))


# --- ambiguous "is" (DR3.2)


def test_two_ambiguous_is_facts_do_not_chain():
    engine = engine_with(("rex", "is", "dog"), ("dog", "is", "species"))
    assert not engine.query("rex", "is", "species")
    assert {str(f) for f in engine.ambiguous()} == {"rex is dog", "dog is species"}


def test_derived_facts_are_not_listed_as_ambiguous():
    engine = engine_with(("rex", "is", "dog"), ("dog", "subclass_of", "mammal"))
    assert engine.query("rex", "is", "mammal")
    assert [str(f) for f in engine.ambiguous()] == ["rex is dog"]


def test_classify_resolves_and_reasons_with_the_new_predicate():
    engine = engine_with(("rex", "is", "dog"), ("dog", "is", "species"), ("dog", "subclass_of", "mammal"))
    engine.classify(Fact("rex", "is", "dog"), "instance_of")
    assert engine.query("rex", "instance_of", "mammal")
    assert not engine.query("rex", "is", "dog")
    engine.classify(Fact("dog", "is", "species"), "instance_of")
    assert not engine.query("rex", "instance_of", "species")
    assert engine.ambiguous() == []


def test_classify_keeps_the_given_confidence():
    engine = InferenceEngine()
    engine.add_fact(Fact("rex", "is", "dog", confidence=0.7))
    classified = engine.classify(Fact("rex", "is", "dog"), "instance_of")
    assert classified.confidence == pytest.approx(0.7)
    assert engine.query("rex", "instance_of", "dog")[0].confidence == pytest.approx(0.7)


def test_classify_rejects_meanings_that_do_not_fit():
    engine = engine_with(("rex", "not_is", "cat"), ("rain", "is", TRUE))
    with pytest.raises(ValueError):
        engine.classify(Fact("rex", "not_is", "cat"), "subclass_of")
    with pytest.raises(ValueError):
        engine.classify(Fact("rain", "is", TRUE), "instance_of")
    with pytest.raises(KeyError):
        engine.classify(Fact("fido", "is", "dog"), "instance_of")


def test_contradiction_between_membership_and_non_membership():
    engine = engine_with(("rex", "instance_of", "cat"), ("rex", "not_instance_of", "cat"))
    assert engine.query("rex", "contradiction", "cat")
