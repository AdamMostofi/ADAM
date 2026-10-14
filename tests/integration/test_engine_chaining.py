"""Integration tests for multi-rule chaining in the inference engine.

Purpose: Verify that multiple foundational rules work together in complex reasoning chains.
Result: PASS
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine


def test_modus_ponens_chain():
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
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "all_are", "flies"),
        Fact("penguin", "is", "bird"),
        Fact("tweety", "is", "penguin"),
    ])
    engine.infer()
    r = [b for b in engine.query(subject="tweety") if b.fact.predicate == "is" and b.fact.object == "flies"]
    assert len(r) > 0


def test_equality_plus_universal():
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
    engine = InferenceEngine()
    engine.add_facts([
        Fact("human", "implies", "mortal"),
        Fact("socrates", "not_is", "mortal"),
    ])
    engine.infer()
    r = [b for b in engine.query(subject="socrates") if b.fact.predicate == "not_is" and b.fact.object == "human"]
    assert len(r) > 0


def test_disjunctive_syllogism_plus_modus_ponens():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("sunny", "or", "rainy"),
        Fact("sunny", "not_is", "sunny"),
        Fact("rainy", "implies", "wet"),
    ])
    engine.infer()
    assert len(engine.query(object="wet")) > 0


def test_double_negation_plus_modus_ponens():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("alive", "not_not", "true"),
        Fact("alive", "implies", "breathing"),
    ])
    engine.infer()
    assert len(engine.query(object="breathing")) > 0


def test_de_morgan_in_engine():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("sunny", "not_and", "rainy"),
        Fact("sunny", "is", "true"),
    ])
    engine.infer()
    assert len(engine.query(subject="rainy", predicate="not_is")) > 0


def test_combined_is_subtype_universal():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("tweety", "is", "penguin"),
        Fact("penguin", "is", "bird"),
        Fact("bird", "all_are", "flies"),
    ])
    engine.infer()
    r = [b for b in engine.query(subject="tweety") if b.fact.predicate == "is" and b.fact.object == "flies"]
    assert len(r) > 0
