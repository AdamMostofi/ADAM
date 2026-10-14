"""Stress tests: knowledge graph with large datasets.

Purpose: Verify graph performance with many nodes and edges.
Result: PASS
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.graph import KnowledgeGraph


def test_graph_1000_nodes():
    """Tests graph with 1000 nodes completes quickly. Result: PASS."""
    graph = KnowledgeGraph()
    facts = [Fact(f"n{i}", "is", f"n{i+1}") for i in range(1000)]
    start = time.time()
    graph.add_facts(facts)
    elapsed = time.time() - start
    assert elapsed < 5.0
    assert len(graph.get_all_nodes()) == 1001


def test_graph_1000_path_finding():
    """Tests path finding in 1000-node graph. Result: PASS."""
    graph = KnowledgeGraph()
    facts = [Fact(f"n{i}", "is", f"n{i+1}") for i in range(1000)]
    graph.add_facts(facts)
    start = time.time()
    path = graph.find_path("n0", "n999")
    elapsed = time.time() - start
    assert path is not None and len(path) == 1000
    assert elapsed < 5.0


def test_graph_1000_get_related():
    """Tests get_related in 1000-node graph. Result: PASS."""
    graph = KnowledgeGraph()
    facts = [Fact(f"n{i}", "is", f"n{i+1}") for i in range(1000)]
    graph.add_facts(facts)
    start = time.time()
    related = graph.get_related("n500", hops=10)
    elapsed = time.time() - start
    assert len(related) > 0
    assert elapsed < 5.0
