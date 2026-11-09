"""Semantic index: fact embeddings in one SQLite file, searched with numpy.

Chosen in Stage 0.5 (#32) over LanceDB and sqlite-vec; see
docs/design/vector-index.md for the benchmark and the rules used.

- One row per fact id (writing the same id again replaces it), so the file
  grows linearly and never accumulates versions.
- Vectors are normalized, so a dot product is cosine similarity.
- All vectors are kept in memory for search (about 1.5 KB per fact at 384
  dimensions); reconsider sqlite-vec if ADAM grows past ~50,000 facts.
- The index is derived data: `rebuild()` recreates it from the fact store.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from typing import Any, Iterable

import numpy as np

from kernel.facts import Fact

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def model_cache_dir() -> str:
    """Where fastembed keeps models: FASTEMBED_CACHE_PATH, else ~/.cache/fastembed.

    fastembed's own default is the system temp folder, which WSL clears on
    restart, so the model would be downloaded again after every restart.
    """
    return os.environ.get("FASTEMBED_CACHE_PATH") or os.path.join(os.path.expanduser("~"), ".cache", "fastembed")


class SemanticIndex:
    def __init__(self, db_path: str = "adam_vectors.db", model_name: str = DEFAULT_MODEL):
        if os.path.isdir(db_path):
            raise RuntimeError(
                f"{db_path} is a directory (an old LanceDB store). The vector index is now a single "
                "SQLite file; reset the store (Stage 0.6) or pass a new path."
            )
        self.db_path = db_path
        self.model_name = model_name
        self._model = None
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._ids: list[str] | None = None
        self._rows: list[dict[str, Any]] | None = None
        self._matrix: np.ndarray | None = None

    # ------------------------------------------------------------- embedding
    def _load_model(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=self.model_name, cache_dir=model_cache_dir())
        return self._model

    def _embed(self, text: str) -> list[float]:
        model = self._load_model()
        return [float(x) for x in list(model.embed([text]))[0]]

    def _vector(self, text: str) -> np.ndarray:
        vector = np.asarray(self._embed(text), dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    # --------------------------------------------------------------- storage
    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            directory = os.path.dirname(os.path.abspath(self.db_path))
            os.makedirs(directory, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS vectors (
                       id TEXT PRIMARY KEY,
                       subject TEXT NOT NULL,
                       predicate TEXT NOT NULL,
                       object TEXT NOT NULL,
                       confidence REAL,
                       source TEXT,
                       timestamp REAL,
                       embedding BLOB NOT NULL
                   )"""
            )
            self._conn.commit()
        return self._conn

    def _invalidate(self) -> None:
        self._ids = self._rows = self._matrix = None

    def _row(self, fact_id: int | str, fact: Fact, vector: np.ndarray) -> tuple:
        return (str(fact_id), fact.subject, fact.predicate, fact.object, fact.confidence,
                fact.source.value, fact.timestamp, vector.astype(np.float32).tobytes())

    def store(self, fact_id: int, fact: Fact) -> None:
        vector = self._vector(str(fact))
        with self._lock:
            conn = self._db()
            with conn:
                conn.execute("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             self._row(fact_id, fact, vector))
            self._invalidate()

    def rebuild(self, facts: Iterable[tuple[int, Fact]]) -> int:
        """Replace the whole index with embeddings of `facts` (id, fact). Returns the row count."""
        rows = [self._row(fact_id, fact, self._vector(str(fact))) for fact_id, fact in facts]
        with self._lock:
            conn = self._db()
            with conn:
                conn.execute("DELETE FROM vectors")
                conn.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
            self._invalidate()
            return self.count()

    def _load(self) -> None:
        if self._matrix is not None:
            return
        rows = self._db().execute(
            "SELECT id, subject, predicate, object, confidence, source, timestamp, embedding FROM vectors ORDER BY rowid"
        ).fetchall()
        self._ids = [r[0] for r in rows]
        self._rows = [{"id": r[0], "subject": r[1], "predicate": r[2], "object": r[3],
                       "confidence": r[4], "source": r[5], "timestamp": r[6]} for r in rows]
        if rows:
            self._matrix = np.vstack([np.frombuffer(r[7], dtype=np.float32) for r in rows])
        else:
            self._matrix = np.zeros((0, 0), dtype=np.float32)

    # ---------------------------------------------------------------- search
    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            self._load()
            if not self._ids or limit <= 0:
                return []
            query_vector = self._vector(query)
            if query_vector.shape[0] != self._matrix.shape[1]:
                raise RuntimeError(
                    f"query has {query_vector.shape[0]} dimensions but the index has {self._matrix.shape[1]}; "
                    "the embedding model changed, so rebuild the index"
                )
            scores = self._matrix @ query_vector
            k = min(limit, len(scores))
            top = np.argpartition(-scores, k - 1)[:k]
            top = top[np.argsort(-scores[top], kind="stable")]
            return [{**self._rows[i], "_distance": float(1.0 - scores[i])} for i in top]

    def search_by_fact(self, fact: Fact, limit: int = 10) -> list[dict[str, Any]]:
        return self.search(str(fact), limit)

    def delete(self, fact_id: int) -> None:
        with self._lock:
            conn = self._db()
            with conn:
                conn.execute("DELETE FROM vectors WHERE id = ?", (str(fact_id),))
            self._invalidate()

    def count(self) -> int:
        with self._lock:
            return self._db().execute("SELECT COUNT(*) FROM vectors").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
            self._conn = None
            self._invalidate()
