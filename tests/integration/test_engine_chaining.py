"""Integration tests for multi-rule chaining in the inference engine.

Purpose: Verify that multiple foundational rules work together in complex reasoning chains.
Result: PASS
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine


def test_modus_ponens_chain():
    """Tests 3-step modus ponens chain: a->b->c->d + a is a => a is d. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b"),
        Fact("b", "implies", "c"),
        Fact("c", "implies", "d"),
        Fact("a", "is", "a"),
    ])
    engine.infer()
    deduced = {str(b.fact) for b in engine.query()}
    assert "a is b" in deduced
    assert "a is c" in deduced
    assert "a is d" in deduced


def test_transitivity_plus_modus_ponens():
    """Tests 4-step transitivity + modus ponens: a->b->c->d->e + a is a => a is e. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b"),
        Fact("b", "implies", "c"),
        Fact("c", "implies", "d"),
        Fact("d", "implies", "e"),
        Fact("a", "is", "a"),
    ])
    engine.infer()
    assert len(engine.query(subject="a", predicate="implies", object="e")) > 0
    assert len(engine.query(subject="a", predicate="is", object="e")) > 0


def test_subtype_plus_universal():
    """Subclass + universal: bird all_are flies + penguin subclass_of bird + tweety instance_of penguin => tweety instance_of flies."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "all_are", "flies"),
        Fact("penguin", "subclass_of", "bird"),
        Fact("tweety", "instance_of", "penguin"),
    ])
    engine.infer()
    r = [b for b in engine.query(subject="tweety") if b.fact.predicate == "instance_of" and b.fact.object == "flies"]
    assert len(r) > 0


def test_equality_plus_universal():
    """Tests equality + universal: john=jack + jack is person + person all_are mortal => john is mortal. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("john", "equals", "jack"),
        Fact("jack", "is", "person"),
        Fact("person", "all_are", "mortal"),
    ])
    engine.infer()
    r = [b for b in engine.query(subject="john") if b.fact.predicate == "is" and b.fact.object == "mortal"]
    assert len(r) > 0


def test_modus_tollens_in_engine():
    """Tests modus tollens in engine: human->mortal + socrates not_is mortal => socrates not_is human. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("human", "implies", "mortal"),
        Fact("socrates", "not_is", "mortal"),
    ])
    engine.infer()
    r = [b for b in engine.query(subject="socrates") if b.fact.predicate == "not_is" and b.fact.object == "human"]
    assert len(r) > 0


def test_disjunctive_syllogism_plus_modus_ponens():
    """sunny or rainy + not sunny + rainy -> wet gives "wet is true".

    Stage 1.1: this test used to pass vacuously (the input fact "rainy implies
    wet" already has object "wet"), and "not sunny" was written incorrectly.
    """
    engine = InferenceEngine()
    engine.add_facts([
        Fact("sunny", "or", "rainy"),
        Fact("sunny", "not_is", "true"),
        Fact("rainy", "implies", "wet"),
    ])
    engine.infer()
    assert engine.query("rainy", "is", "true")
    assert engine.query("wet", "is", "true")


def test_double_negation_plus_modus_ponens():
    """alive not_not true + alive -> breathing gives "breathing is true" (was vacuous before Stage 1.1)."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("alive", "not_not", "true"),
        Fact("alive", "implies", "breathing"),
    ])
    engine.infer()
    assert engine.query("alive", "is", "true")
    assert engine.query("breathing", "is", "true")


def test_de_morgan_in_engine():
    """not(sunny and rainy) + sunny gives "rainy not_is true", and nothing false about sunny.

    Stage 1.1: this used to pass only because the unsound de_morgan_and
    asserted both negations, including the false "sunny not_is true".
    """
    engine = InferenceEngine()
    engine.add_facts([
        Fact("sunny", "not_and", "rainy"),
        Fact("sunny", "is", "true"),
    ])
    engine.infer()
    assert engine.query("rainy", "not_is", "true")
    assert not engine.query("sunny", "not_is", "true")
    assert not engine.query(predicate="contradiction")


def test_combined_is_subtype_universal():
    """Membership through a hierarchy: tweety instance_of penguin, penguin subclass_of bird, bird all_are flies => tweety instance_of flies (Stage 1.3)."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("tweety", "instance_of", "penguin"),
        Fact("penguin", "subclass_of", "bird"),
        Fact("bird", "all_are", "flies"),
    ])
    engine.infer()
    r = [b for b in engine.query(subject="tweety") if b.fact.predicate == "instance_of" and b.fact.object == "flies"]
    assert len(r) > 0


def test_ambiguous_is_chain_does_not_combine():
    """Stage 1.3 (#29): "tweety is penguin" + "penguin is bird" could be rex/dog/species; nothing follows."""
    engine = InferenceEngine()
    engine.add_facts([Fact("tweety", "is", "penguin"), Fact("penguin", "is", "bird"), Fact("bird", "all_are", "flies")])
    engine.infer()
    assert not engine.query("tweety", "is", "bird")
    assert engine.query("penguin", "is", "flies")  # sound under either reading of "penguin is bird"
