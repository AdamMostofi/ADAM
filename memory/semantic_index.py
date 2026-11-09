"""Semantic index: fact embeddings in one SQLite file, searched with numpy.

Chosen in Stage 0.5 (#32) over LanceDB and sqlite-vec; see
docs/design/vector-index.md for the benchmark and the rules used.

- One row per fact id (writing the same id again replaces it), so the file
  grows linearly and never accumulates versions.
- Vectors are normalized, so a dot product is cosine similarity.
- All vectors are kept in memory for search (about 1.5 KB per fact at 384
  dimensions); reconsider sqlite-vec if ADAM grows past ~50,000 facts.
- The index is derived data: `rebuild()` recreates it from the fact store.

Embeddings come from all-MiniLM-L6-v2 in its int8 ONNX form, run directly
with onnxruntime and its memory arena off. In the Stage 0.5 benchmark this
matched the best quality tested while using about 165 MB less than the
same model through fastembed.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Any, Iterable

import numpy as np

from kernel.facts import Fact

DEFAULT_MODEL = "all-MiniLM-L6-v2-int8"
MODEL_REPO = "Xenova/all-MiniLM-L6-v2"
MODEL_REVISION = "751bff37182d3f1213fa05d7196b954e230abad9"  # pinned commit (Apache-2.0)
MODEL_FILE = "onnx/model_quantized.onnx"
TOKENIZER_FILE = "tokenizer.json"
MAX_TOKENS = 256
EMBEDDING_DIM = 384
INDEX_SCHEMA_VERSION = 1


class IndexMismatchError(RuntimeError):
    """The index was built with a different model, dimension, or schema; rebuild it."""


class MiniLMEncoder:
    """Sentence embeddings: tokenize, run the ONNX model, mean-pool, normalize.

    Files are fetched once from the pinned commit into the Hugging Face cache
    (~/.cache/huggingface, or HF_HOME), which survives restarts. Set
    HF_HUB_OFFLINE=1 to forbid any network access once they are cached.
    """

    def __init__(self):
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        model_path = hf_hub_download(MODEL_REPO, MODEL_FILE, revision=MODEL_REVISION)
        tokenizer_path = hf_hub_download(MODEL_REPO, TOKENIZER_FILE, revision=MODEL_REVISION)
        options = ort.SessionOptions()
        options.enable_cpu_mem_arena = False
        self._session = ort.InferenceSession(model_path, options, providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}
        self._tokenizer = Tokenizer.from_file(tokenizer_path)
        self._tokenizer.enable_truncation(max_length=MAX_TOKENS)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")

    def embed(self, texts: list[str]) -> np.ndarray:
        encoded = self._tokenizer.encode_batch(texts)
        ids = np.array([e.ids for e in encoded], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
        hidden = self._session.run(None, {k: v for k, v in feeds.items() if k in self._inputs})[0]
        pooled = (hidden * mask[..., None]).sum(axis=1) / np.clip(mask.sum(axis=1, keepdims=True), 1, None)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return (pooled / np.where(norms == 0, 1, norms)).astype(np.float32)


class SemanticIndex:
    def __init__(self, db_path: str = "adam_vectors.db", model_name: str = DEFAULT_MODEL):
        if os.path.isdir(db_path):
            raise RuntimeError(
                f"{db_path} is a directory (an old LanceDB store). The vector index is now a single "
                "SQLite file; reset the store (Stage 0.6) or pass a new path."
            )
        if model_name != DEFAULT_MODEL:
            raise ValueError(f"unsupported embedding model {model_name!r}; ADAM uses {DEFAULT_MODEL!r}")
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
            self._model = MiniLMEncoder()
        return self._model

    def _embed(self, text: str) -> list[float]:
        return [float(x) for x in self._load_model().embed([text])[0]]

    def _vector(self, text: str) -> np.ndarray:
        vector = np.asarray(self._embed(text), dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    # --------------------------------------------------------------- storage
    def _expected_meta(self) -> dict[str, str]:
        return {"schema_version": str(INDEX_SCHEMA_VERSION), "embedding_model": self.model_name,
                "embedding_dim": str(EMBEDDING_DIM)}

    def _write_meta(self, conn: sqlite3.Connection) -> None:
        for key, value in self._expected_meta().items():
            conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
        conn.execute("INSERT OR IGNORE INTO meta VALUES ('created_at', ?)", (time.strftime("%Y-%m-%dT%H:%M:%S%z"),))

    def _db(self, check: bool = True) -> sqlite3.Connection:
        if self._conn is None:
            directory = os.path.dirname(os.path.abspath(self.db_path))
            os.makedirs(directory, exist_ok=True)
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute(
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
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            stored = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            rows = conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
            if not stored and rows == 0:
                self._write_meta(conn)
            elif check:
                expected = self._expected_meta()
                wrong = {k: stored.get(k) for k in expected if stored.get(k) != expected[k]}
                if wrong:
                    conn.close()
                    raise IndexMismatchError(
                        f"{self.db_path} was built with {wrong} but ADAM now uses {expected}. "
                        "Rebuild the index from the fact store (MemorySystem.rebuild_index())."
                    )
            conn.commit()
            self._conn = conn
        return self._conn

    def meta(self) -> dict[str, str]:
        with self._lock:
            return dict(self._db().execute("SELECT key, value FROM meta").fetchall())

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
            conn = self._db(check=False)
            with conn:
                conn.execute("DELETE FROM vectors")
                conn.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
                conn.execute("DELETE FROM meta WHERE key != 'created_at'")
                self._write_meta(conn)
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
