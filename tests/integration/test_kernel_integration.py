"""Integration tests for V0.2 Kernel — multi-step reasoning and edge cases.

Verifies the kernel produces correct results on complex reasoning chains.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine


def test_multi_step_deduction_correctness():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", source=Source.USER),
        Fact("b", "implies", "c", source=Source.USER),
        Fact("c", "implies", "d", source=Source.USER),
        Fact("d", "implies", "e", source=Source.USER),
        Fact("a", "is", "a", source=Source.USER),
    ])
    engine.infer()
    assert len(engine.query(subject="a", predicate="is", object="e")) > 0
    assert len(engine.query(subject="a", predicate="implies", object="e")) > 0


def test_confidence_propagation_accuracy():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", confidence=0.9, source=Source.USER),
        Fact("b", "implies", "c", confidence=0.9, source=Source.USER),
        Fact("a", "is", "a", confidence=1.0, source=Source.USER),
    ])
    engine.infer()
    result = [b for b in engine.query(subject="a", predicate="is", object="c")]
    assert len(result) > 0
    assert abs(result[0].confidence - 0.81) < 0.001


def test_all_rules_together():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "all_are", "flies", source=Source.USER),
        Fact("penguin", "is", "bird", source=Source.USER),
        Fact("tweety", "is", "penguin", source=Source.USER),
        Fact("op", "equals", "operation", source=Source.USER),
        Fact("operation", "is", "process", source=Source.USER),
    ])
    engine.infer()
    assert len(engine.query(subject="tweety", predicate="is", object="bird")) > 0
    assert len(engine.query(subject="tweety", predicate="is", object="flies")) > 0
    assert len(engine.query(subject="op", predicate="is", object="process")) > 0


def test_contradiction_detection_in_deductions():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "all_are", "flies", source=Source.USER),
        Fact("penguin", "is", "bird", source=Source.USER),
        Fact("penguin", "not_is", "flies", source=Source.USER),
    ])
    engine.infer()
    contradictions = engine.query(predicate="contradiction")
    assert len(contradictions) > 0


def test_retract_removes_all_dependents():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", source=Source.USER),
        Fact("b", "implies", "c", source=Source.USER),
        Fact("c", "implies", "d", source=Source.USER),
        Fact("a", "is", "a", source=Source.USER),
    ])
    engine.infer()
    assert len(engine.query(subject="a", predicate="is", object="d")) > 0
    engine.retract(Fact("a", "implies", "b"))
    assert len(engine.query(subject="a", predicate="is", object="d")) == 0


def test_query_by_object():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("cat", "is", "mammal", source=Source.USER),
        Fact("dog", "is", "mammal", source=Source.USER),
        Fact("shark", "is", "fish", source=Source.USER),
    ])
    assert len(engine.query(object="mammal")) == 2


def test_deep_chain_100_hops():
    engine = InferenceEngine()
    facts = [Fact(f"n{i}", "implies", f"n{i+1}") for i in range(100)]
    facts.append(Fact("n0", "is", "n0"))
    engine.add_facts(facts)
    engine.infer(max_iterations=5000)
    assert len(engine.query(subject="n0", predicate="is", object="n100")) > 0
