"""Fuzz tests: malformed and edge-case inputs.

Purpose: Verify system doesn't crash on unexpected inputs.
Result: PASS
"""
import sys, os, random, string
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine
from kernel.graph import KnowledgeGraph


def test_special_characters_in_fields():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a!@#", "is", "$%^"),
        Fact("hello world", "implies", "foo bar"),
    ])
    engine.infer()
    assert len(engine.query(subject="a!@#")) > 0


def test_very_long_strings():
    engine = InferenceEngine()
    long_str = "x" * 10000
    engine.add_facts([Fact(long_str, "is", long_str)])
    engine.infer()
    assert len(engine.query(subject=long_str)) > 0


def test_unicode_characters():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("café", "is", "résumé"),
        Fact("日本語", "implies", "中文"),
    ])
    engine.infer()
    assert len(engine.query(subject="café")) > 0


def test_numeric_strings():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("123", "is", "456"),
        Fact("0", "implies", "1"),
    ])
    engine.infer()
    assert len(engine.query(subject="123")) > 0


def test_confidence_boundary_zero():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", confidence=0.0),
        Fact("a", "is", "a", confidence=0.0),
    ])
    engine.infer()
    for b in engine.query():
        assert b.confidence >= 0.0


def test_confidence_boundary_one():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", confidence=1.0),
        Fact("a", "is", "a", confidence=1.0),
    ])
    engine.infer()
    for b in engine.query():
        assert b.confidence <= 1.0


def test_random_facts_no_crash():
    engine = InferenceEngine()
    random.seed(42)
    for _ in range(100):
        subj = "".join(random.choices(string.ascii_lowercase, k=5))
        pred = random.choice(["is", "implies", "all_are", "equals", "or"])
        obj = "".join(random.choices(string.ascii_lowercase, k=5))
        conf = random.random()
        engine.add_fact(Fact(subj, pred, obj, confidence=conf))
    engine.infer(max_iterations=100)


def test_empty_string_rejected():
    try:
        Fact("", "is", "y")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_whitespace_only_rejected():
    try:
        Fact("   ", "is", "y")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
