"""Integration tests for fact retraction in the inference engine.

Purpose: Verify that removing a fact also removes all beliefs derived from it.
Result: PASS
Fix: Was not properly removing dependent beliefs. Now clears and re-derives from remaining user facts.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine


def test_retract_removes_dependents():
    """Tests retracting a rule removes dependent deductions: retract bird->flies => tweety is bird stays, tweety is flies removed. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "implies", "flies"),
        Fact("tweety", "is", "bird"),
    ])
    engine.infer()
    assert len(engine.query(subject="tweety")) > 1
    engine.retract(Fact("bird", "implies", "flies"))
    assert len(engine.query(subject="tweety")) == 1
    assert engine.query(subject="tweety")[0].fact.object == "bird"


def test_retract_removes_chain():
    """Tests retracting removes chain deductions: retract a->b => a is c removed. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b"),
        Fact("b", "implies", "c"),
        Fact("a", "is", "a"),
    ])
    engine.infer()
    assert len(engine.query(object="c")) > 0
    engine.retract(Fact("a", "implies", "b"))
    remaining_c = engine.query(object="c")
    assert all(b.fact.subject != "a" for b in remaining_c)


def test_retract_nonexistent():
    """Tests retracting a fact that doesn't exist is a no-op. Result: PASS."""
    engine = InferenceEngine()
    engine.add_fact(Fact("a", "is", "b"))
    engine.retract(Fact("x", "is", "y"))
    assert len(engine.query()) == 1


def test_retract_all_leaves_empty():
    """Tests retracting the only fact leaves empty engine. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "is", "b", source=Source.USER)])
    engine.retract(Fact("a", "is", "b"))
    assert len(engine.query()) == 0


def test_retract_preserves_independent_facts():
    """Tests retracting one rule preserves independent facts: retract a->b => c is d stays. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b"),
        Fact("c", "is", "d"),
    ])
    engine.infer()
    engine.retract(Fact("a", "implies", "b"))
    assert len(engine.query(subject="c")) > 0
