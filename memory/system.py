"""MemorySystem — main API wrapping all 3 storage layers.

Provides perfect recall, semantic search, and auto-connection.
"""
from __future__ import annotations

from dataclasses import replace

import collections
import threading
import time

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine, key_of
from memory.exact_store import ExactStore
from memory.semantic_index import DEFAULT_MODEL, SemanticIndex
from memory.connection_graph import ConnectionGraph
from memory.attention import AttentionBank


def _embedding_similarity(semantic_index: SemanticIndex, text_a: str, text_b: str) -> float:
    vec_a = semantic_index._embed(text_a)
    vec_b = semantic_index._embed(text_b)
    import numpy as np
    a = np.array(vec_a)
    b = np.array(vec_b)
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(dot / norm)


# Agenda entries a restart may process (Stage 1.6, #36). Enough to saturate stores far larger than
# today's (20,000 given facts take ~60,000), so a restarted ADAM knows all it knew; a pathological
# store stops here with a warning and continues during chat turns.
STARTUP_INFERENCE_BUDGET = 200_000


class MemorySystem:
    def __init__(
        self,
        db_path: str = "adam_memory.db",
        lance_path: str = "adam_vectors.db",
        embedding_model: str = DEFAULT_MODEL,
        restore: bool = True,
    ):
        self.exact = ExactStore(db_path)
        self.semantic = SemanticIndex(lance_path, embedding_model)
        self.graph = ConnectionGraph()
        self.engine = InferenceEngine()
        # Session-only by design (Stage 1.6, #36): short-term attention is the focus of the
        # current conversation and is meant to fade; see docs/design/restart.md.
        self.attention = AttentionBank()
        self.lock = threading.RLock()
        self.startup: dict = {}
        self._stored_keys: set[str] | None = None  # cache of stored fact keys, loaded on first use
        if restore:
            self.restore()

    def restore(self) -> dict:
        """Rebuild the graph and the engine from the store (DS1: SQLite is the source of truth).

        * Graph: every stored row is replayed in id order, exactly as store()
          built it (its edge, then its "related" connections), so the graph
          matches the one before the restart. Superseded rows keep their
          connections but not their own edge.
        * Engine: every given (not derived) row that isn't superseded, with
          all its origins; then inference. Derived facts come back by
          inference, with their derivations.
        Startup is read-only: it writes nothing to the store, so the facts
        are the same before and after a restart and loading a save doesn't
        change it. Conclusions the store doesn't have yet are stored the
        next time ADAM writes (settle()).

        Returns and records the startup cost in self.startup.
        """
        start = time.perf_counter()
        with self.lock:
            self.engine = InferenceEngine()
            self.graph = ConnectionGraph()
            rows = self.exact.get_all_with_ids()
            superseded = self.exact.superseded_ids()
            origins = self.exact.all_origins()
            by_subject: dict[str, list[Fact]] = collections.defaultdict(list)
            by_object: dict[str, list[Fact]] = collections.defaultdict(list)
            for fact_id, fact in rows:
                by_subject[fact.subject].append(fact)
                by_object[fact.object].append(fact)
                if fact_id not in superseded:
                    self.graph.add_fact(fact)
                if self.graph.similarity_fn is None:
                    self.graph.similarity_fn = lambda a, b: _embedding_similarity(self.semantic, a, b)
                    self.graph.similarity_threshold = 0.7
                # store() calls auto_connect(fact, rows with its subject + rows with its object). Every
                # such row shares a term with the fact, so each connection is (fact.subject, row.object):
                # connecting the distinct objects gives the same edges in linear time.
                for obj in sorted({f.object for f in by_subject[fact.subject]} | {fact.object}):
                    self.graph.add_connection(fact.subject, obj)
            given_rows = [(i, f) for i, f in rows if f.source != Source.DEDUCED and i not in superseded]
            self.engine.add_facts([replace(f, origin=o) for i, f in given_rows for o in (origins.get(i) or [""])])
            inferred = self.engine.infer(max_iterations=STARTUP_INFERENCE_BUDGET)
            self._stored_keys = self.exact.all_keys()
            self.startup = {
                "rows": len(rows), "given_facts": len(given_rows), "superseded": len(superseded),
                "beliefs": len(self.engine.beliefs), "inferred": len(inferred),
                "not_yet_stored": len(self.unstored(self.engine)), "saturated": self.engine.saturated,
                "seconds": round(time.perf_counter() - start, 4),
            }
            return self.startup

    def _known_keys(self) -> set[str]:
        if self._stored_keys is None:
            self._stored_keys = self.exact.all_keys()
        return self._stored_keys

    def unstored(self, engine) -> list:
        """Keys of engine beliefs the store doesn't have yet."""
        from memory.exact_store import fact_key
        known = self._known_keys()
        return sorted(k for k, b in engine.beliefs.items() if fact_key(b.fact) not in known)

    def settle(self, engine, max_iterations: int = 10000) -> int:
        """Infer, then store every belief the store doesn't have yet. Returns how many were stored.

        Compares all beliefs with the stored keys (cached) rather than
        trusting infer()'s return value, which a retract in between resets,
        and which misses conclusions found at startup.
        """
        with self.lock:
            engine.infer(max_iterations=max_iterations)
            missing = self.unstored(engine)
            if missing:
                self.store_beliefs(engine, missing)
            return len(missing)

    def store(self, fact: Fact) -> int:
        """Store a given fact once; storing it again only updates confidence and timestamp.

        Derived facts go through store_beliefs(), which keeps their derivations.
        """
        from memory.exact_store import fact_key

        with self.lock:
            fact_id, created = self.exact.upsert(fact)
            if self._stored_keys is not None:
                self._stored_keys.add(fact_key(fact))
            self._index_new(fact_id, fact, created)
            return fact_id

    def store_beliefs(self, engine, keys) -> list[int]:
        """Persist engine beliefs with their derivations, and everything they rest on, in one transaction.

        Derived premises are stored with their own derivations first, so each
        stored derived fact has a path back to its inputs (Stage 1.4, #30).
        Returns the stored IDs of `keys`, in order.
        """
        from kernel.engine import key_of

        with self.lock:
            entries, index, seen = [], {}, set()

            def visit(k):
                if k in seen or k not in engine.beliefs:
                    return
                seen.add(k)
                belief = engine.beliefs[k]
                for proof in belief.proofs:
                    for premise in proof.premises:
                        visit(premise)
                derivations = [
                    {"rule": p.rule, "rule_version": p.rule_version, "confidence": p.confidence,
                     "premises": [engine.beliefs[q].fact for q in p.premises]}
                    for p in belief.proofs if all(q in engine.beliefs for q in p.premises)
                ]
                index[k] = len(entries)
                entries.append((belief.fact, derivations))
                # Every origin it was given by (one row, many origins).
                entries.extend((replace(belief.fact, origin=o), []) for o in sorted(belief.origins)
                               if o != belief.fact.origin)

            keys = list(keys)
            for k in keys:
                visit(k)
            results = self.exact.store_derived(entries)
            if self._stored_keys is not None:
                from memory.exact_store import fact_key
                self._stored_keys.update(fact_key(fact) for fact, _ in entries)
            for (fact, _), (fact_id, created) in zip(entries, results):
                self._index_new(fact_id, fact, created)
            return [results[index[k]][0] for k in keys if k in index]

    def store_inferred(self, engine, facts: list[Fact]) -> list[int]:
        """Persist facts an engine derived (e.g. infer()'s return value), with their derivations."""
        from kernel.engine import key_of
        return self.store_beliefs(engine, [key_of(f) for f in facts])

    def explain(self, fact_id: int) -> list[dict] | None:
        """Walk a stored fact back to the inputs it rests on (ExactStore.trace)."""
        return self.exact.trace(fact_id)

    def _index_new(self, fact_id: int, fact: Fact, created: bool) -> None:
        """Graph and vectors for a stored row, as store() does."""
        if not created:
            self.semantic.store(fact_id, self.exact.get(fact_id) or fact)
            return
        self.graph.add_fact(fact)
        self.semantic.store(fact_id, fact)
        if self.graph.similarity_fn is None:
            self.graph.similarity_fn = lambda a, b: _embedding_similarity(self.semantic, a, b)
            self.graph.similarity_threshold = 0.7
        related = self.exact.find_by_subject(fact.subject)
        related.extend(self.exact.find_by_object(fact.object))
        self.graph.auto_connect(fact, related)

    def store_with_proof(self, fact: Fact, proof_chain: list[str]) -> int:
        with self.lock:
            fact_id, created = self.exact.upsert(fact, proof_chain)
            if created:
                self.graph.add_fact(fact)
            self.semantic.store(fact_id, self.exact.get(fact_id) or fact)
            return fact_id

    def recall(self, query: str, limit: int = 10) -> list[Fact]:
        with self.lock:
            results = self.exact.search_text(query)
            if not results:
                semantic_results = self.semantic.search(query, limit)
                results = []
                for r in semantic_results:
                    try:
                        fact_id = int(r["id"])
                    except (ValueError, KeyError):
                        continue
                    fact = self.exact.get(fact_id)
                    if fact:
                        results.append(fact)
            self.attention.decay()
            for fact in results:
                self.attention.stimulate(str(fact))
            return self.attention.rank(results)

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
        with self.lock:
            return self.exact.count()

    def save(self, path: str, include_vectors: bool = True) -> None:
        import shutil, os, json
        with self.lock:
            os.makedirs(path, exist_ok=True)
            shutil.copy(self.exact.db_path, os.path.join(path, "memory.db"))
            if include_vectors and os.path.isfile(self.semantic.db_path):
                shutil.copy(self.semantic.db_path, os.path.join(path, "vectors.db"))
            graph_data = {"nodes": list(self.graph.get_all_nodes()), "edges": [(u, v, d) for u, v, d in self.graph.get_all_edges()]}
            with open(os.path.join(path, "graph.json"), "w") as f:
                json.dump(graph_data, f)

    @classmethod
    def load(cls, path: str, lance_path: str | None = None) -> "MemorySystem":
        import os
        db_path = os.path.join(path, "memory.db")
        if lance_path is None:
            lance_path = os.path.join(path, "vectors.db")
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database file not found: {db_path}")
        return cls(db_path=db_path, lance_path=lance_path)  # restores engine and graph

    def rebuild_index(self) -> int:
        """Recreate the semantic index from the fact store. Returns the number of vectors."""
        with self.lock:
            return self.semantic.rebuild(self.exact.get_all_with_ids())

    def close(self) -> None:
        self.exact.close()
        self.semantic.close()
