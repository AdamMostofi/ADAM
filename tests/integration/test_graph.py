"""Integration tests for the knowledge graph.

Purpose: Verify graph storage, querying, path finding, and cycle handling.
Result: PASS
Fix: Changed from DiGraph to MultiDiGraph to handle multiple edges between same nodes with different predicates.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.graph import KnowledgeGraph


def test_add_and_get_nodes():
    graph = KnowledgeGraph()
    graph.add_facts([Fact("a", "is", "b"), Fact("b", "is", "c")])
    assert set(graph.get_all_nodes()) == {"a", "b", "c"}


def test_add_and_get_edges():
    graph = KnowledgeGraph()
    graph.add_facts([Fact("a", "is", "b")])
    assert len(graph.get_all_edges()) == 1


def test_multiple_edges_same_nodes():
    graph = KnowledgeGraph()
    graph.add_facts([
        Fact("a", "is", "b"),
        Fact("a", "equals", "b"),
        Fact("a", "implies", "b"),
    ])
    assert len(graph.get_all_edges()) == 3


def test_find_path_simple():
    graph = KnowledgeGraph()
    graph.add_facts([
        Fact("a", "is", "b"),
        Fact("b", "is", "c"),
        Fact("c", "is", "d"),
    ])
    path = graph.find_path("a", "d")
    assert path == ["a", "b", "c", "d"]


def test_find_path_multiple_paths():
    graph = KnowledgeGraph()
    graph.add_facts([
        Fact("a", "is", "b"),
        Fact("b", "is", "d"),
        Fact("a", "is", "c"),
        Fact("c", "is", "d"),
    ])
    path = graph.find_path("a", "d")
    assert path is not None and path[0] == "a" and path[-1] == "d"


def test_find_path_disconnected():
    graph = KnowledgeGraph()
    graph.add_facts([Fact("a", "is", "b"), Fact("c", "is", "d")])
    assert graph.find_path("a", "d") is None


def test_get_related_one_hop():
    graph = KnowledgeGraph()
    graph.add_facts([Fact("a", "is", "b"), Fact("b", "is", "c")])
    related = graph.get_related("a", hops=1)
    assert len(related) == 1


def test_get_related_two_hops():
    graph = KnowledgeGraph()
    graph.add_facts([Fact("a", "is", "b"), Fact("b", "is", "c")])
    related = graph.get_related("a", hops=2)
    assert len(related) == 2


def test_get_related_cycle():
    graph = KnowledgeGraph()
    graph.add_facts([
        Fact("a", "is", "b"),
        Fact("b", "is", "c"),
        Fact("c", "is", "a"),
    ])
    related = graph.get_related("a", hops=5)
    assert len(related) > 0


def test_get_related_self_loop():
    graph = KnowledgeGraph()
    graph.add_facts([Fact("a", "is", "a")])
    related = graph.get_related("a", hops=1)
    assert len(related) >= 1


def test_get_related_nonexistent_node():
    graph = KnowledgeGraph()
    graph.add_facts([Fact("a", "is", "b")])
    assert graph.get_related("nonexistent") == []


def test_large_graph_path():
    graph = KnowledgeGraph()
    facts = [Fact(f"n{i}", "is", f"n{i+1}") for i in range(100)]
    graph.add_facts(facts)
    path = graph.find_path("n0", "n99")
    assert path is not None and len(path) == 100
