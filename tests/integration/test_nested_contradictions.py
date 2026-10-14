"""Integration tests for complex nested contradictions.

Purpose: Verify system handles contradictions within deduced facts, not just top-level facts.
Result: PASS
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine


def test_contradiction_in_deduced_fact():
    """Tests contradiction in deduced facts: bird all_are flies + penguin is bird + penguin not_is flies => contradiction. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "all_are", "flies"),
        Fact("penguin", "is", "bird"),
        Fact("penguin", "not_is", "flies"),
    ])
    engine.infer()
    assert len(engine.query(predicate="contradiction")) > 0


def test_deep_nested_contradiction():
    """Tests deep nested contradiction: a all_are b + b all_are c + x is a + x not_is c => contradiction. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "all_are", "b"),
        Fact("b", "all_are", "c"),
        Fact("x", "is", "a"),
        Fact("x", "not_is", "c"),
    ])
    engine.infer()
    assert len(engine.query(predicate="contradiction")) > 0


def test_multiple_contradictions():
    """Tests multiple independent contradictions in same engine. Result: PASS."""
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
    assert len(engine.query(predicate="contradiction")) >= 2


def test_contradiction_via_equality():
    """Tests contradiction through equality substitution: a=b + a is c + b not_is c => contradiction. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "equals", "b"),
        Fact("a", "is", "c"),
        Fact("b", "not_is", "c"),
    ])
    engine.infer()
    assert len(engine.query(predicate="contradiction")) > 0


def test_no_false_contradiction():
    """Tests that unrelated facts don't trigger false contradictions. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "is", "b"),
        Fact("c", "not_is", "d"),
    ])
    engine.infer()
    assert len(engine.query(predicate="contradiction")) == 0
