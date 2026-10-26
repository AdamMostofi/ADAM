"""Goal-directed backward chaining: prove a goal without forward saturation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.engine import InferenceEngine
from kernel.facts import Fact


def test_prove_through_implication_chain():
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "implies", "b"), Fact("b", "implies", "c")])
    proof = engine.prove("a", "is", "c")
    assert proof is not None
    assert len(engine.beliefs) == 2


def test_prove_implies_transitivity():
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "implies", "b"), Fact("b", "implies", "c")])
    assert engine.prove("a", "implies", "c") is not None


def test_prove_universal_instantiation():
    engine = InferenceEngine()
    engine.add_facts([Fact("tweety", "is", "bird"), Fact("bird", "all_are", "flies")])
    assert engine.prove("tweety", "is", "flies") is not None


def test_prove_direct_belief():
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "is", "b")])
    assert engine.prove("a", "is", "b") is not None


def test_prove_unknown_returns_none():
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "implies", "b")])
    assert engine.prove("a", "is", "zzz") is None


def test_prove_survives_cycles():
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "implies", "b"), Fact("b", "implies", "a")])
    assert engine.prove("a", "implies", "zzz", max_depth=8) is None
