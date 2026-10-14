"""MemorySystem — main API wrapping all 3 storage layers.

Provides perfect recall, semantic search, and auto-connection.
"""
from __future__ import annotations

from kernel.facts import Fact
from kernel.engine import InferenceEngine
from memory.exact_store import ExactStore
from memory.semantic_index import SemanticIndex
from memory.connection_graph import ConnectionGraph


class MemorySystem:
    def __init__(
        self,
        db_path: str = "adam_memory.db",
        lance_path: str = "adam_vectors.lance",
        embedding_model: str = "google/embeddinggemma-300m",
    ):
        self.exact = ExactStore(db_path)
        self.semantic = SemanticIndex(lance_path, embedding_model)
        self.graph = ConnectionGraph()
        self.engine = InferenceEngine()

    def store(self, fact: Fact) -> int:
        fact_id = self.exact.store(fact)
        self.graph.add_fact(fact)
        self.semantic.store(fact_id, fact)
        related = self.exact.find_by_subject(fact.subject)
        related.extend(self.exact.find_by_object(fact.object))
        self.graph.auto_connect(fact, related)
        return fact_id

    def store_with_proof(self, fact: Fact, proof_chain: list[str]) -> int:
        fact_id = self.exact.store(fact, proof_chain)
        self.graph.add_fact(fact)
        self.semantic.store(fact_id, fact)
        return fact_id

    def recall(self, query: str, limit: int = 10) -> list[Fact]:
        results = self.exact.search_text(query)
        if results:
            return results
        semantic_results = self.semantic.search(query, limit)
        facts = []
        for r in semantic_results:
            fact_id = int(r["id"])
            fact = self.exact.get(fact_id)
            if fact:
                facts.append(fact)
        return facts

    def search(self, query: str, limit: int = 10) -> list[dict]:
        return self.semantic.search(query, limit)

    def get_context(self, fact: Fact, hops: int = 2) -> list[tuple[str, str, dict]]:
        return self.graph.get_related(fact.subject, hops)

    def connect(self, fact_a: Fact, fact_b: Fact) -> None:
        self.graph.add_connection(fact_a.subject, fact_b.object, "related", 1.0)

    def get_related_facts(self, subject: str) -> list[Fact]:
        return self.exact.find_by_subject(subject)

    def get_all_facts(self) -> list[Fact]:
        return self.exact.get_all()

    def count(self) -> int:
        return self.exact.count()

    def save(self, path: str) -> None:
        import shutil, os
        os.makedirs(path, exist_ok=True)
        shutil.copy(self.exact.db_path, os.path.join(path, "memory.db"))
        import json
        graph_data = {"nodes": list(self.graph.get_all_nodes()), "edges": [(u, v, d) for u, v, d in self.graph.get_all_edges()]}
        with open(os.path.join(path, "graph.json"), "w") as f:
            json.dump(graph_data, f)

    @classmethod
    def load(cls, path: str) -> "MemorySystem":
        import shutil, os
        db_path = os.path.join(path, "memory.db")
        lance_path = os.path.join(path, "vectors.lance")
        system = cls(db_path=db_path, lance_path=lance_path)
        user_facts = system.exact.get_user_facts()
        system.engine.add_facts(user_facts)
        system.engine.infer()
        for fact in system.exact.get_all():
            system.graph.add_fact(fact)
        return system

    def close(self) -> None:
        self.exact.close()
        self.semantic.close()
