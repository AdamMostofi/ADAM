"""Integration tests for complex nested contradictions.

Purpose: Verify system handles contradictions within deduced facts, not just top-level facts.
Result: PASS
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine


def test_contradiction_in_deduced_fact():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "all_are", "flies"),
        Fact("penguin", "is", "bird"),
        Fact("penguin", "not_is", "flies"),
    ])
    engine.infer()
    contradictions = engine.query(predicate="contradiction")
    assert len(contradictions) > 0


def test_deep_nested_contradiction():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "all_are", "b"),
        Fact("b", "all_are", "c"),
        Fact("x", "is", "a"),
        Fact("x", "not_is", "c"),
    ])
    engine.infer()
    contradictions = engine.query(predicate="contradiction")
    assert len(contradictions) > 0


def test_multiple_contradictions():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "all_are", "flies"),
        Fact("penguin", "is", "bird"),
        Fact("penguin", "not_is", "flies"),
        Fact("fish", "all_are", "swims"),
        Fact("shark", "is", "fish"),
        Fact("shark", "not_is", "swims"),
    ])
    engine.infer()
    contradictions = engine.query(predicate="contradiction")
    assert len(contradictions) >= 2


def test_contradiction_via_equality():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "equals", "b"),
        Fact("a", "is", "c"),
        Fact("b", "not_is", "c"),
    ])
    engine.infer()
    contradictions = engine.query(predicate="contradiction")
    assert len(contradictions) > 0


def test_no_false_contradiction():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "is", "b"),
        Fact("c", "not_is", "d"),
    ])
    engine.infer()
    contradictions = engine.query(predicate="contradiction")
    assert len(contradictions) == 0
