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


class ExactStore:
    def __init__(self, db_path: str = "adam_memory.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    def store(self, fact: Fact, proof_chain: list[str] | None = None) -> int:
        fact_text = str(fact)
        proof_json = json.dumps(proof_chain) if proof_chain else None
        metadata = json.dumps({})
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO facts (subject, predicate, object, confidence, source, timestamp, fact_text, proof_chain, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (fact.subject, fact.predicate, fact.object, fact.confidence,
                 fact.source.value, fact.timestamp, fact_text, proof_json, metadata)
            )
            return cursor.lastrowid

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

    def close(self) -> None:
        pass
