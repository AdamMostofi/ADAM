"""Variable-bearing queries over beliefs (MeTTa-style match)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.engine import InferenceEngine
from kernel.facts import Fact


def _engine():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("socrates", "is", "man"),
        Fact("plato", "is", "man"),
        Fact("man", "all_are", "mortal"),
    ])
    return engine


def test_wildcard_subject_binds_all():
    engine = _engine()
    matches = engine.query_pattern(predicate="is", object="man")
    subjects = {b["?s"] for _, b in matches}
    assert subjects == {"socrates", "plato"}


def test_repeated_variable_requires_equality():
    engine = _engine()
    matches = engine.query_pattern("?x", "is", "?x")
    assert matches == []


def test_literal_with_variable_object():
    engine = _engine()
    matches = engine.query_pattern("socrates", "is", "?o")
    assert len(matches) == 1
    assert matches[0][1]["?o"] == "man"


def test_no_match_returns_empty():
    engine = _engine()
    assert engine.query_pattern("nobody", "is", "man") == []
