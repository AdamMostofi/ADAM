"""Knowledge graph for deduced knowledge (graph.py).

Stores what ADAM has deduced and can reason over.
Separate from source_graph.py which stores raw book material.
Uses MultiDiGraph to handle multiple edges between same nodes.
"""

from __future__ import annotations

import networkx as nx

from kernel.facts import Fact


class KnowledgeGraph:
    def __init__(self):
        self.graph = nx.MultiDiGraph()

    def add_fact(self, fact: Fact) -> None:
        self.graph.add_edge(
            fact.subject,
            fact.object,
            predicate=fact.predicate,
            confidence=fact.confidence,
            source=fact.source.value,
        )

    def add_facts(self, facts: list[Fact]) -> None:
        for f in facts:
            self.add_fact(f)

    def get_related(self, node: str, hops: int = 1) -> list[tuple[str, str, dict]]:
        """Get all edges within N hops of a node. Handles cycles and self-loops."""
        if node not in self.graph:
            return []
        related = []
        seen_edges = set()
        visited = set()
        current = {node}
        for _ in range(hops):
            next_level = set()
            for n in current:
                for successor in self.graph.successors(n):
                    edge_key = (n, successor)
                    if edge_key not in seen_edges:
                        for key, data in self.graph[n][successor].items():
                            related.append((n, successor, data))
                        seen_edges.add(edge_key)
                    if successor not in visited:
                        next_level.add(successor)
                for predecessor in self.graph.predecessors(n):
                    edge_key = (predecessor, n)
                    if edge_key not in seen_edges:
                        for key, data in self.graph[predecessor][n].items():
                            related.append((predecessor, n, data))
                        seen_edges.add(edge_key)
                    if predecessor not in visited:
                        next_level.add(predecessor)
            visited.update(current)
            current = next_level
            if not current:
                break
        return related

    def find_path(self, source: str, target: str) -> list[str] | None:
        """Find shortest path between two nodes."""
        try:
            return nx.shortest_path(self.graph, source, target)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def get_all_nodes(self) -> list[str]:
        return list(self.graph.nodes())

    def get_all_edges(self) -> list[tuple[str, str, dict]]:
        return [(u, v, data) for u, v, data in self.graph.edges(data=True)]
