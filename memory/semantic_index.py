"""Semantic index layer using LanceDB + EmbeddingGemma.

Stores embeddings for similarity search.
LanceDB handles persistence, metadata, and vector search automatically.
"""
from __future__ import annotations

from typing import Any

import lancedb
import numpy as np

from kernel.facts import Fact, Source


class SemanticIndex:
    def __init__(self, db_path: str = "adam_vectors.lance", model_name: str = "google/embeddinggemma-300m"):
        self.db_path = db_path
        self.model_name = model_name
        self._model = None
        self._db = None
        self._table = None

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def _get_table(self):
        if self._table is None:
            self._db = lancedb.connect(self.db_path)
            try:
                self._table = self._db.open_table("facts")
            except Exception:
                self._load_model()
                sample = self._model.encode("sample", normalize_embeddings=True)
                dim = len(sample)
                self._table = self._db.create_table(
                    "facts",
                    data=[{
                        "id": "placeholder",
                        "vector": np.zeros(dim, dtype=np.float32).tolist(),
                        "subject": "",
                        "predicate": "",
                        "object": "",
                        "confidence": 0.0,
                        "source": "",
                        "timestamp": 0.0,
                    }]
                )
        return self._table

    def _embed(self, text: str) -> list[float]:
        model = self._load_model()
        embedding = model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    def store(self, fact_id: int, fact: Fact) -> None:
        table = self._get_table()
        fact_text = str(fact)
        vector = self._embed(fact_text)
        table.add([{
            "id": str(fact_id),
            "vector": vector,
            "subject": fact.subject,
            "predicate": fact.predicate,
            "object": fact.object,
            "confidence": fact.confidence,
            "source": fact.source.value,
            "timestamp": fact.timestamp,
        }])

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        table = self._get_table()
        query_vector = self._embed(query)
        results = table.search(query_vector).limit(limit).to_list()
        return results

    def search_by_fact(self, fact: Fact, limit: int = 10) -> list[dict[str, Any]]:
        return self.search(str(fact), limit)

    def delete(self, fact_id: int) -> None:
        table = self._get_table()
        table.delete(f"id = '{fact_id}'")

    def count(self) -> int:
        table = self._get_table()
        return table.count_rows()

    def close(self) -> None:
        self._table = None
        self._db = None
