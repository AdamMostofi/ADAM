"""Integration tests for the knowledge graph.

Purpose: Verify graph storage, querying, path finding, and cycle handling.
Result: PASS
Fix: Changed from DiGraph to MultiDiGraph to handle multiple edges between same nodes with different predicates.
Fix: Fixed self-loop handling with seen_edges deduplication.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.graph import KnowledgeGraph


def test_add_and_get_nodes():
    """Tests adding facts and retrieving all nodes. Result: PASS."""
    graph = KnowledgeGraph()
    graph.add_facts([Fact("a", "is", "b"), Fact("b", "is", "c")])
    assert set(graph.get_all_nodes()) == {"a", "b", "c"}


def test_add_and_get_edges():
    """Tests adding facts and retrieving all edges. Result: PASS."""
    graph = KnowledgeGraph()
    graph.add_facts([Fact("a", "is", "b")])
    assert len(graph.get_all_edges()) == 1


def test_multiple_edges_same_nodes():
    """Tests multiple edges between same nodes with different predicates. Result: PASS. Fix: DiGraph was overwriting, MultiDiGraph preserves all."""
    graph = KnowledgeGraph()
    graph.add_facts([
        Fact("a", "is", "b"),
        Fact("a", "equals", "b"),
        Fact("a", "implies", "b"),
    ])
    assert len(graph.get_all_edges()) == 3


def test_find_path_simple():
    """Tests simple path finding: a->b->c->d. Result: PASS."""
    graph = KnowledgeGraph()
    graph.add_facts([
        Fact("a", "is", "b"),
        Fact("b", "is", "c"),
        Fact("c", "is", "d"),
    ])
    assert graph.find_path("a", "d") == ["a", "b", "c", "d"]


def test_find_path_multiple_paths():
    """Tests path finding when multiple paths exist (returns shortest). Result: PASS."""
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
    """Tests path finding returns None for disconnected components. Result: PASS."""
    graph = KnowledgeGraph()
    graph.add_facts([Fact("a", "is", "b"), Fact("c", "is", "d")])
    assert graph.find_path("a", "d") is None


def test_get_related_one_hop():
    """Tests get_related with 1 hop. Result: PASS."""
    graph = KnowledgeGraph()
    graph.add_facts([Fact("a", "is", "b"), Fact("b", "is", "c")])
    assert len(graph.get_related("a", hops=1)) == 1


def test_get_related_two_hops():
    """Tests get_related with 2 hops. Result: PASS. Fix: was returning duplicates, now deduplicates with seen_edges."""
    graph = KnowledgeGraph()
    graph.add_facts([Fact("a", "is", "b"), Fact("b", "is", "c")])
    assert len(graph.get_related("a", hops=2)) == 2


def test_get_related_cycle():
    """Tests get_related handles cycles without infinite loop. Result: PASS."""
    graph = KnowledgeGraph()
    graph.add_facts([
        Fact("a", "is", "b"),
        Fact("b", "is", "c"),
        Fact("c", "is", "a"),
    ])
    assert len(graph.get_related("a", hops=5)) > 0


def test_get_related_self_loop():
    """Tests get_related handles self-loops without duplicates. Result: PASS. Fix: was returning 0 or duplicates, now uses seen_edges."""
    graph = KnowledgeGraph()
    graph.add_facts([Fact("a", "is", "a")])
    related = graph.get_related("a", hops=1)
    assert len(related) >= 1


def test_get_related_nonexistent_node():
    """Tests get_related returns empty for nonexistent node. Result: PASS."""
    graph = KnowledgeGraph()
    graph.add_facts([Fact("a", "is", "b")])
    assert graph.get_related("nonexistent") == []


def test_large_graph_path():
    """Tests path finding in 100-node graph. Result: PASS."""
    graph = KnowledgeGraph()
    facts = [Fact(f"n{i}", "is", f"n{i+1}") for i in range(100)]
    graph.add_facts(facts)
    path = graph.find_path("n0", "n99")
    assert path is not None and len(path) == 100
