"""Knowledge graph for deduced knowledge (graph.py).

Stores what ADAM has deduced and can reason over.
Separate from source_graph.py which stores raw book material.
"""

from __future__ import annotations

import networkx as nx

from kernel.facts import Fact


class KnowledgeGraph:
    def __init__(self):
        self.graph = nx.DiGraph()

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
        """Get all edges within N hops of a node. Handles cycles."""
        if node not in self.graph:
            return []
        related = []
        visited = {node}
        current = {node}
        for _ in range(hops):
            next_level = set()
            for n in current:
                for successor in self.graph.successors(n):
                    if successor not in visited:
                        related.append((n, successor, self.graph[n][successor]))
                        next_level.add(successor)
                for predecessor in self.graph.predecessors(n):
                    if predecessor not in visited:
                        related.append((predecessor, n, self.graph[predecessor][n]))
                        next_level.add(predecessor)
            visited.update(next_level)
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
        return list(self.graph.edges(data=True))
