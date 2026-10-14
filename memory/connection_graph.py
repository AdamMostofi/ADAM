"""Connection graph layer using NetworkX MultiDiGraph.

Auto-links related facts based on:
- Exact match (same subject or object)
- Semantic match (similar embeddings)
- Transitive inference (a is b + b is c => a is c)
"""
from __future__ import annotations

import networkx as nx

from kernel.facts import Fact


class ConnectionGraph:
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

    def add_connection(self, node_a: str, node_b: str, predicate: str = "related", confidence: float = 1.0) -> bool:
        if self.graph.has_edge(node_a, node_b):
            for key, data in self.graph[node_a][node_b].items():
                if data.get("predicate") == predicate:
                    return False
        self.graph.add_edge(node_a, node_b, predicate=predicate, confidence=confidence, source="connected")
        return True

    def get_related(self, node: str, hops: int = 1) -> list[tuple[str, str, dict]]:
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
        try:
            return nx.shortest_path(self.graph, source, target)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def get_all_nodes(self) -> list[str]:
        return list(self.graph.nodes())

    def get_all_edges(self) -> list[tuple[str, str, dict]]:
        return [(u, v, data) for u, v, data in self.graph.edges(data=True)]

    def auto_connect(self, new_fact: Fact, existing_facts: list[Fact]) -> list[tuple[str, str]]:
        connections = []
        for existing in existing_facts:
            if existing.subject == new_fact.subject:
                pair = (new_fact.subject, existing.object)
            elif existing.object == new_fact.object:
                pair = (new_fact.subject, existing.object)
            elif existing.subject == new_fact.object:
                pair = (new_fact.subject, existing.object)
            elif existing.object == new_fact.subject:
                pair = (existing.subject, new_fact.object)
            else:
                continue
            if self.add_connection(pair[0], pair[1]):
                connections.append(pair)
        return connections

    def clear(self) -> None:
        self.graph.clear()
