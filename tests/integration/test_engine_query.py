"""Integration tests for engine query capabilities.

Purpose: Verify filtering by subject, predicate, and object.
Result: PASS
Fix: Added object-based query (was missing).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine


def test_query_by_subject():
    """Tests filtering by subject only. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([Fact("cat", "is", "mammal"), Fact("dog", "is", "mammal")])
    assert len(engine.query(subject="cat")) == 1


def test_query_by_predicate():
    """Tests filtering by predicate only. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("cat", "is", "mammal"),
        Fact("dog", "is", "mammal"),
        Fact("shark", "is", "not_mammal"),
    ])
    assert len(engine.query(predicate="is")) == 3


def test_query_by_object():
    """Tests filtering by object only. Result: PASS. Fix: was missing, now supported."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("cat", "is", "mammal"),
        Fact("dog", "is", "mammal"),
        Fact("shark", "is", "fish"),
    ])
    assert len(engine.query(object="mammal")) == 2


def test_query_by_subject_and_predicate():
    """Tests filtering by subject and predicate. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([Fact("cat", "is", "mammal"), Fact("cat", "is", "pet")])
    assert len(engine.query(subject="cat", predicate="is")) == 2


def test_query_empty_returns_empty():
    """Tests that non-matching query returns empty list. Result: PASS."""
    engine = InferenceEngine()
    assert len(engine.query(subject="nonexistent")) == 0


def test_query_no_filters_returns_all():
    """Tests that no filters returns all beliefs. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "is", "b"), Fact("c", "is", "d")])
    assert len(engine.query()) == 2
