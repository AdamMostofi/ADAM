"""Integration tests for engine + graph interaction.

Purpose: Verify data flows correctly between inference engine and knowledge graph.
Result: PASS
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine
from kernel.graph import KnowledgeGraph


def test_engine_results_in_graph():
    """Tests that engine deductions appear in graph with correct path. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "all_are", "flies"),
        Fact("tweety", "is", "bird"),
    ])
    engine.infer()
    graph = KnowledgeGraph()
    for b in engine.beliefs.values():
        graph.add_fact(b.fact)
    assert graph.find_path("tweety", "flies") is not None


def test_graph_reflects_retraction():
    """Tests that graph reflects retraction (path removed). Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "implies", "b"), Fact("a", "is", "a")])
    engine.infer()
    graph = KnowledgeGraph()
    for b in engine.beliefs.values():
        graph.add_fact(b.fact)
    assert graph.find_path("a", "b") is not None
    engine.retract(Fact("a", "implies", "b"))
    graph2 = KnowledgeGraph()
    for b in engine.beliefs.values():
        graph2.add_fact(b.fact)
    assert graph2.find_path("a", "b") is None


def test_graph_with_all_rule_types():
    """Tests graph with facts from multiple rule types (all_are, is, equals). Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "all_are", "flies"),
        Fact("penguin", "is", "bird"),
        Fact("tweety", "is", "penguin"),
        Fact("op", "equals", "operation"),
        Fact("operation", "is", "process"),
    ])
    engine.infer()
    graph = KnowledgeGraph()
    for b in engine.beliefs.values():
        graph.add_fact(b.fact)
    assert len(graph.get_all_nodes()) > 3
    assert len(graph.get_all_edges()) > 3


def test_graph_query_after_complex_reasoning():
    """Tests graph path finding after complex multi-step reasoning. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b"),
        Fact("b", "implies", "c"),
        Fact("c", "implies", "d"),
        Fact("a", "is", "a"),
    ])
    engine.infer()
    graph = KnowledgeGraph()
    for b in engine.beliefs.values():
        graph.add_fact(b.fact)
    assert graph.find_path("a", "d") is not None
