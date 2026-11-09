"""Exact storage layer using SQLite + JSON hybrid.

Every fact stored verbatim, never deleted.
Queryable by any field via SQL indexes.
JSON columns handle proof chains and future metadata.
"""
from __future__ import annotations

import json
import sqlite3
import time

from kernel.facts import Fact, Source

SCHEMA_VERSION = 1


def normalize_term(term: str) -> str:
    """Case- and whitespace-insensitive form of a term, used only for the uniqueness key."""
    return " ".join(term.split()).lower()


def fact_key(fact: Fact) -> str:
    """One key per (subject, predicate, object, source), ignoring case and extra spaces."""
    parts = (normalize_term(fact.subject), normalize_term(fact.predicate),
             normalize_term(fact.object), fact.source.value)
    return "\x1f".join(parts)


class OldSchemaError(RuntimeError):
    """The database predates schema version 1 and must be reset."""


class ExactStore:
    def __init__(self, db_path: str = "adam_memory.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "facts" in tables and version < SCHEMA_VERSION:
                raise OldSchemaError(
                    f"{self.db_path} uses an old fact schema (version {version}) without duplicate "
                    "protection. Run `python scripts/reset_store.py --yes` to back it up and start fresh."
                )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact_key TEXT NOT NULL UNIQUE,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    source TEXT DEFAULT 'user',
                    timestamp REAL,
                    fact_text TEXT,
                    proof_chain TEXT,
                    metadata TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_subject ON facts(subject)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_predicate ON facts(predicate)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_object ON facts(object)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON facts(source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_confidence ON facts(confidence)")
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            conn.execute("INSERT OR IGNORE INTO meta VALUES ('created_at', ?)",
                         (time.strftime("%Y-%m-%dT%H:%M:%S%z"),))
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def meta(self) -> dict[str, str]:
        with sqlite3.connect(self.db_path) as conn:
            return dict(conn.execute("SELECT key, value FROM meta").fetchall())

    def upsert(self, fact: Fact, proof_chain: list[str] | None = None) -> tuple[int, bool]:
        """Store a fact once. Returns (id, created).

        If the same (subject, predicate, object, source) already exists, ignoring
        case and extra spaces, keep the higher confidence, take the newer
        timestamp, and keep any proof chain already recorded.
        """
        key = fact_key(fact)
        proof_json = json.dumps(proof_chain) if proof_chain else None
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT id FROM facts WHERE fact_key = ?", (key,)).fetchone()
            if row is not None:
                conn.execute(
                    """UPDATE facts SET confidence = MAX(confidence, ?), timestamp = MAX(timestamp, ?),
                       proof_chain = COALESCE(proof_chain, ?) WHERE id = ?""",
                    (fact.confidence, fact.timestamp, proof_json, row[0]),
                )
                conn.execute("COMMIT")
                return row[0], False
            cursor = conn.execute(
                """INSERT INTO facts (fact_key, subject, predicate, object, confidence, source, timestamp,
                                      fact_text, proof_chain, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (key, fact.subject, fact.predicate, fact.object, fact.confidence, fact.source.value,
                 fact.timestamp, str(fact), proof_json, json.dumps({})),
            )
            conn.execute("COMMIT")
            return cursor.lastrowid, True
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def store(self, fact: Fact, proof_chain: list[str] | None = None) -> int:
        return self.upsert(fact, proof_chain)[0]

    def get(self, fact_id: int) -> Fact | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT subject, predicate, object, confidence, source, timestamp FROM facts WHERE id = ?", (fact_id,)).fetchone()
        if row is None:
            return None
        return Fact(
            subject=row[0], predicate=row[1], object=row[2],
            confidence=row[3], source=Source(row[4]), timestamp=row[5]
        )

    def get_with_proof(self, fact_id: int) -> tuple[Fact, list[str]] | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT subject, predicate, object, confidence, source, timestamp, proof_chain FROM facts WHERE id = ?",
                (fact_id,)
            ).fetchone()
        if row is None:
            return None
        fact = Fact(
            subject=row[0], predicate=row[1], object=row[2],
            confidence=row[3], source=Source(row[4]), timestamp=row[5]
        )
        proof_chain = json.loads(row[6]) if row[6] else []
        return fact, proof_chain

    def find_by_subject(self, subject: str) -> list[Fact]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT subject, predicate, object, confidence, source, timestamp FROM facts WHERE subject = ?",
                (subject,)
            ).fetchall()
        return [Fact(r[0], r[1], r[2], r[3], Source(r[4]), r[5]) for r in rows]

    def find_by_object(self, obj: str) -> list[Fact]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT subject, predicate, object, confidence, source, timestamp FROM facts WHERE object = ?",
                (obj,)
            ).fetchall()
        return [Fact(r[0], r[1], r[2], r[3], Source(r[4]), r[5]) for r in rows]

    def find_by_predicate(self, predicate: str) -> list[Fact]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT subject, predicate, object, confidence, source, timestamp FROM facts WHERE predicate = ?",
                (predicate,)
            ).fetchall()
        return [Fact(r[0], r[1], r[2], r[3], Source(r[4]), r[5]) for r in rows]

    def get_all(self) -> list[Fact]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT subject, predicate, object, confidence, source, timestamp FROM facts"
            ).fetchall()
        return [Fact(r[0], r[1], r[2], r[3], Source(r[4]), r[5]) for r in rows]

    def get_all_with_ids(self) -> list[tuple[int, Fact]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, subject, predicate, object, confidence, source, timestamp FROM facts ORDER BY id"
            ).fetchall()
        return [(r[0], Fact(r[1], r[2], r[3], r[4], Source(r[5]), r[6])) for r in rows]

    def get_user_facts(self) -> list[Fact]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT subject, predicate, object, confidence, source, timestamp FROM facts WHERE source = 'user'"
            ).fetchall()
        return [Fact(r[0], r[1], r[2], r[3], Source(r[4]), r[5]) for r in rows]

    def search_text(self, query: str) -> list[Fact]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT subject, predicate, object, confidence, source, timestamp FROM facts WHERE fact_text LIKE ?",
                (f"%{query}%",)
            ).fetchall()
        return [Fact(r[0], r[1], r[2], r[3], Source(r[4]), r[5]) for r in rows]

    def count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    def count_by_source(self) -> dict[str, int]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT source, COUNT(*) FROM facts GROUP BY source").fetchall()
        return {source: count for source, count in rows}

    def close(self) -> None:
        pass
