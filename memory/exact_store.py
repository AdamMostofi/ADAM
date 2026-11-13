"""Exact storage layer using SQLite + JSON hybrid.

Every fact stored verbatim, never deleted.
Queryable by any field via SQL indexes.

Derivations (schema 2, Stage 1.4, #30): every derived fact (source
"deduced") is stored with at least one row in `derivations`, which names the
rule, its version, the ordered premise fact IDs and the confidence. The
record is the truth; readable proofs are rendered from it. `trace()` walks
any fact back to the inputs it rests on. The old `proof_chain` text column
is kept for rows written before schema 2 and is no longer written.
"""
from __future__ import annotations

import json
import sqlite3
import time

from kernel.facts import Fact, Source

SCHEMA_VERSION = 3
DERIVED = Source.DEDUCED


class UnderivedFactError(ValueError):
    """A derived fact was stored without any derivation."""


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
            if "facts" in tables and version < 1:
                raise OldSchemaError(
                    f"{self.db_path} uses an old fact schema (version {version}) without duplicate "
                    "protection. Run `python scripts/reset_store.py --yes` to back it up and start fresh."
                )
            if version == SCHEMA_VERSION and {"facts", "derivations", "fact_origins", "meta"} <= tables:
                return  # current schema: opening the store writes nothing (Stage 1.6, #36)
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS derivations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conclusion_id INTEGER NOT NULL REFERENCES facts(id),
                    rule TEXT NOT NULL,
                    rule_version TEXT NOT NULL,
                    premise_ids TEXT NOT NULL,
                    premise_set TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    timestamp REAL NOT NULL,
                    UNIQUE (conclusion_id, rule, premise_set)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_derivation_conclusion ON derivations(conclusion_id)")
            # Schema 3 (Stage 1.5, #31): where each fact came from; one fact can have many origins.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fact_origins (
                    fact_id INTEGER NOT NULL REFERENCES facts(id),
                    origin TEXT NOT NULL,
                    UNIQUE (fact_id, origin)
                )
            """)
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            if 0 < version < SCHEMA_VERSION:
                # Schema 1 -> 2 adds derivations, 2 -> 3 adds fact_origins; existing rows are kept as they are.
                conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                             (f"migrated_from_{version}", time.strftime("%Y-%m-%dT%H:%M:%S%z")))
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
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
        if fact.source == DERIVED:
            raise UnderivedFactError(
                f"{fact} is derived; store it with its derivations (store_derived), "
                "so it keeps a path back to its inputs")
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            result = self._upsert_row(conn, fact, proof_chain)
            conn.execute("COMMIT")
            return result
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @staticmethod
    def _upsert_row(conn, fact: Fact, proof_chain: list[str] | None = None) -> tuple[int, bool]:
        key = fact_key(fact)
        proof_json = json.dumps(proof_chain) if proof_chain else None
        row = conn.execute("SELECT id FROM facts WHERE fact_key = ?", (key,)).fetchone()
        if row is not None:
            conn.execute(
                """UPDATE facts SET confidence = MAX(confidence, ?), timestamp = MAX(timestamp, ?),
                   proof_chain = COALESCE(proof_chain, ?) WHERE id = ?""",
                (fact.confidence, fact.timestamp, proof_json, row[0]),
            )
            if fact.origin:
                conn.execute("INSERT OR IGNORE INTO fact_origins VALUES (?, ?)", (row[0], fact.origin))
            return row[0], False
        cursor = conn.execute(
            """INSERT INTO facts (fact_key, subject, predicate, object, confidence, source, timestamp,
                                  fact_text, proof_chain, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (key, fact.subject, fact.predicate, fact.object, fact.confidence, fact.source.value,
             fact.timestamp, str(fact), proof_json, json.dumps({})),
        )
        if fact.origin:
            conn.execute("INSERT OR IGNORE INTO fact_origins VALUES (?, ?)", (cursor.lastrowid, fact.origin))
        return cursor.lastrowid, True

    def store_derived(self, entries: list[tuple[Fact, list[dict]]]) -> list[tuple[int, bool]]:
        """Store facts and their derivations in one transaction. Returns (id, created) per entry.

        Each entry is (fact, derivations); a derivation is a dict with "rule",
        "rule_version", "premises" (the premise Facts, in order) and
        "confidence". Premises are stored too if they aren't yet; a derived
        premise must itself be an entry, so nothing derived enters without a
        derivation. Storing the same derivation again adds no row (it keeps
        the higher confidence).
        """
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            derived_keys = {fact_key(f) for f, derivations in entries if derivations}
            for fact, derivations in entries:
                if fact.source == DERIVED and not derivations:
                    raise UnderivedFactError(f"{fact} is derived but has no derivation")
                for d in derivations:
                    for premise in d["premises"]:
                        if premise.source == DERIVED and fact_key(premise) not in derived_keys:
                            raise UnderivedFactError(f"premise {premise} of {fact} is derived but not stored with it")
            results = [self._upsert_row(conn, fact) for fact, _ in entries]
            now = time.time()
            for (fact, derivations), (conclusion_id, _) in zip(entries, results):
                for d in derivations:
                    premise_ids = [self._upsert_row(conn, p)[0] for p in d["premises"]]
                    conn.execute(
                        """INSERT INTO derivations (conclusion_id, rule, rule_version, premise_ids, premise_set,
                                                    confidence, timestamp)
                           VALUES (?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT (conclusion_id, rule, premise_set)
                           DO UPDATE SET confidence = MAX(confidence, excluded.confidence)""",
                        (conclusion_id, d["rule"], d["rule_version"], json.dumps(premise_ids),
                         json.dumps(sorted(set(premise_ids))), d["confidence"], now),
                    )
            conn.execute("COMMIT")
            return results
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def derivations_of(self, fact_id: int) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, rule, rule_version, premise_ids, confidence, timestamp FROM derivations "
                "WHERE conclusion_id = ? ORDER BY id", (fact_id,)).fetchall()
        return [{"id": r[0], "rule": r[1], "rule_version": r[2], "premise_ids": json.loads(r[3]),
                 "confidence": r[4], "timestamp": r[5]} for r in rows]

    def trace(self, fact_id: int) -> list[dict] | None:
        """Walk a fact back to the inputs it rests on.

        Returns steps, inputs first: {"id", "fact", "derivation"} where
        "derivation" is None for an input (any fact not derived) and
        otherwise the derivation used, whose premises all appear earlier.
        The walk is well-founded, so cycles among derivations can't trap it.
        Returns None if the fact doesn't exist, or if a derived fact has no
        derivation that reaches inputs (see underived()).
        """
        facts: dict[int, Fact] = {}
        derivations: dict[int, list[dict]] = {}
        stack = [fact_id]
        while stack:
            current = stack.pop()
            if current in facts:
                continue
            fact = self.get(current)
            if fact is None:
                return None
            facts[current] = fact
            if fact.source == DERIVED:
                derivations[current] = self.derivations_of(current)
                for d in derivations[current]:
                    stack.extend(d["premise_ids"])
        explained: dict[int, dict | None] = {i: None for i, f in facts.items() if f.source != DERIVED}
        order = sorted(explained)
        while fact_id not in explained:
            ready = []
            for i in sorted(set(facts) - set(explained)):
                usable = [d for d in derivations[i] if all(p in explained for p in d["premise_ids"])]
                if usable:
                    ready.append((i, max(usable, key=lambda d: (d["confidence"], -d["id"]))))
            if not ready:
                return None
            for i, d in ready:
                explained[i] = d
                order.append(i)
        used, stack = set(), [fact_id]
        while stack:
            i = stack.pop()
            if i not in used:
                used.add(i)
                if explained[i] is not None:
                    stack.extend(explained[i]["premise_ids"])
        return [{"id": i, "fact": facts[i], "derivation": explained[i]} for i in order if i in used]

    def render_trace(self, fact_id: int) -> list[str]:
        """trace() as readable lines, rendered from the records."""
        steps = self.trace(fact_id) or []
        by_id = {s["id"]: s["fact"] for s in steps}
        lines = []
        for step in steps:
            d = step["derivation"]
            if d is None:
                lines.append(f"[given] {step['fact']}")
            else:
                premises = " + ".join(str(by_id[p]) for p in d["premise_ids"])
                lines.append(f"[{d['rule']}] {premises} -> {step['fact']}")
        return lines

    def underived(self) -> list[int]:
        """IDs of derived facts with no derivation (only possible for rows written before schema 2)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id FROM facts WHERE source = ? AND id NOT IN (SELECT conclusion_id FROM derivations) "
                "ORDER BY id", (DERIVED.value,)).fetchall()
        return [r[0] for r in rows]

    def all_keys(self) -> set[str]:
        """Every stored fact_key (one query; used to find what the store is missing)."""
        with sqlite3.connect(self.db_path) as conn:
            return {r[0] for r in conn.execute("SELECT fact_key FROM facts")}

    def has(self, fact: Fact) -> bool:
        """Whether this fact (same terms, ignoring case and spacing, and same source) is stored."""
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT 1 FROM facts WHERE fact_key = ?", (fact_key(fact),)).fetchone() is not None

    def supersede(self, fact: Fact, by_id: int) -> int | None:
        """Mark a stored fact as replaced by another row (e.g. a classified "is"). Nothing is deleted.

        Superseded rows stay in the store and in the graph's history, but a
        restart doesn't give them to the engine again (Stage 1.6, #36).
        Returns the superseded row's id, or None if the fact isn't stored.
        """
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT id, metadata FROM facts WHERE fact_key = ?", (fact_key(fact),)).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return None
            metadata = json.loads(row[1] or "{}")
            metadata["superseded_by"] = by_id
            conn.execute("UPDATE facts SET metadata = ? WHERE id = ?", (json.dumps(metadata), row[0]))
            conn.execute("COMMIT")
            return row[0]
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def superseded_ids(self) -> set[int]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id FROM facts WHERE json_extract(metadata, '$.superseded_by') IS NOT NULL").fetchall()
        return {r[0] for r in rows}

    def all_origins(self) -> dict[int, list[str]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT fact_id, origin FROM fact_origins ORDER BY fact_id, origin").fetchall()
        origins: dict[int, list[str]] = {}
        for fact_id, origin in rows:
            origins.setdefault(fact_id, []).append(origin)
        return origins

    def origins_of(self, fact_id: int) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT origin FROM fact_origins WHERE fact_id = ? ORDER BY origin",
                                (fact_id,)).fetchall()
        return [r[0] for r in rows]

    def count_derivations(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM derivations").fetchone()[0]

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
        if fact.source == DERIVED:
            return fact, self.render_trace(fact_id)
        proof_chain = json.loads(row[6]) if row[6] else []  # rows written before schema 2
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
