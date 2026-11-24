"""The source library: Markdown sources, their passages, and passage search (Stage 4.2, #24).

The Data-Vault in the console's words (decision D3.4); `source_library` in code.

**What it keeps**, through the storage contract (`memory.store_contract`), as engine records:
- **A source** (`source` record), keyed by the SHA-256 of the file's bytes. Its body is the file's text as the
  store keeps it: the engine redacts anything shaped like a secret before storing, so `stored_sha256` is the
  hash of the kept text and `redacted` says whether it differs from the file. Its fields hold the name (the path
  inside the workspace), the hashes, the size, the passage count and the status.
- **A passage** (`passage` record) per paragraph, keyed by the source's hash and the passage's ordinal. Its
  fields hold the source, the ordinal, the character offsets `start` and `end` in the kept text, and the
  passage's SHA-256. The passage text itself is never in the fields, which aren't encrypted: it is
  `text[start:end]` of the source's body, which is.

**Passage search** (decision D3.2) is SQLite FTS5 with BM25 ranking, in an index file beside the store
(`adam_memory.passages.db`): tables `sources`, `passages` and `passage_fts`. The index is derived: it is rebuilt
from the records whenever it lacks a source, so deleting it loses nothing.

**Ingest is idempotent.** A file whose bytes are already a source adds nothing, under any name. Ingest writes
the source first (status `ingesting`), reads its kept text back, cuts the passages from that text, then writes
every passage and the finished source in one transaction. An ingest interrupted between the two resumes the
next time; it never adds a passage twice, because a passage's key is its source and ordinal.

**What it doesn't do** (out of scope for Stage 4.2): other formats than Markdown (D3.1), embeddings or any
model, upload from the web UI (D3.3: the CLI only), claims.

Usage:
    python -m memory.source_library ingest <file.md> [--workspace DIR]
    python -m memory.source_library search "<query>" [--limit N]
    python -m memory.source_library list
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from memory.store_contract import FactStore

SOURCE, PASSAGE = "source", "passage"
MARKDOWN_SUFFIXES = (".md", ".markdown")
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_LIMIT = 100
_BLANK_LINE = re.compile(r"\n[ \t]*\r?\n")
_WORD = re.compile(r"\w+")


class SourceError(ValueError):
    """A source can't be ingested: outside the workspace, not Markdown, not UTF-8, too big, or no records."""


@dataclass(frozen=True)
class Passage:
    key: str
    source: str
    name: str
    ordinal: int
    start: int
    end: int
    sha256: str
    text: str
    score: float | None = None


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def paragraphs(text: str) -> list[tuple[int, int]]:
    """Character spans (start, end) of the paragraphs in Markdown text: runs of lines separated by one or more
    blank lines, without their surrounding whitespace. `text[start:end]` is each paragraph exactly."""
    spans, pos = [], 0
    bounds = [(m.start(), m.end()) for m in _BLANK_LINE.finditer(text)] + [(len(text), len(text))]
    for cut, resume in bounds:
        start, end = pos, cut
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            spans.append((start, end))
        pos = resume
    return spans


def fts5_available() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
        finally:
            conn.close()
        return True
    except sqlite3.OperationalError:
        return False


def passage_key(source_sha: str, ordinal: int) -> str:
    return f"{source_sha}#{ordinal}"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    key TEXT PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL, stored_sha256 TEXT NOT NULL,
    redacted INTEGER NOT NULL, size INTEGER NOT NULL, passages INTEGER NOT NULL, ingested_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS passages (
    rowid INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, source TEXT NOT NULL REFERENCES sources(key),
    ordinal INTEGER NOT NULL, start INTEGER NOT NULL, "end" INTEGER NOT NULL, sha256 TEXT NOT NULL, text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_passages_source ON passages(source, ordinal);
CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(
    text, content='passages', content_rowid='rowid', tokenize='porter unicode61'
);
"""


class SourceLibrary:
    def __init__(self, store: FactStore, index_path: str | Path, workspace: str | Path | None = None):
        if not store.supports_records:
            raise SourceError(f"the source library needs a store that keeps records; the {store.backend!r} "
                              "store doesn't (unset ADAM_STORE, or set it to 'engine')")
        if not fts5_available():
            raise SourceError("this Python's SQLite has no FTS5, which passage search needs")
        self.store = store
        self.index_path = Path(index_path)
        self.workspace = Path(workspace or os.environ.get("ADAM_WORKSPACE") or os.getcwd()).resolve()
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
        finally:
            conn.close()
        self.sync()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.index_path, timeout=30)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ------------------------------------------------------------ ingest
    def resolve(self, path: str | Path) -> Path:
        """The real path of a source file, refused unless it is a Markdown file inside the workspace."""
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        try:
            real = candidate.resolve(strict=True)
        except (FileNotFoundError, RuntimeError) as err:
            raise SourceError(f"no such file: {path}") from err
        if not real.is_relative_to(self.workspace):
            raise SourceError(f"{path} is outside the workspace ({self.workspace}); only files inside it can be "
                              "ingested")
        if not real.is_file():
            raise SourceError(f"{path} is not a file")
        if real.suffix.lower() not in MARKDOWN_SUFFIXES:
            raise SourceError(f"{path} is not Markdown ({', '.join(MARKDOWN_SUFFIXES)}); other formats come later")
        return real

    def ingest(self, path: str | Path) -> dict:
        """Add a Markdown file to the library, once. Returns what happened: the source's key and name, whether
        it was new, how many passages this call added, and how many the source has."""
        real = self.resolve(path)
        if real.stat().st_size > MAX_SOURCE_BYTES:
            raise SourceError(f"{path} is larger than {MAX_SOURCE_BYTES // (1024 * 1024)} MB")
        data = real.read_bytes()
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as err:
            raise SourceError(f"{path} is not UTF-8 text") from err
        key, name = sha256(data), real.relative_to(self.workspace).as_posix()

        existing = self.store.get_record(SOURCE, key)
        if existing is not None and existing["fields"]["status"] == "ingested":
            self._index(existing)
            return {"source": key, "name": existing["fields"]["name"], "created": False, "passages_added": 0,
                    "passages": existing["fields"]["passages"]}
        created = existing is None
        if created:
            self.store.put_record(SOURCE, key, {"name": name, "sha256": key, "size": len(data), "status": "ingesting"},
                                  body=data, index=("name", "status"))
        added = self._finish(key)
        record = self.store.get_record(SOURCE, key)
        self._index(record)
        return {"source": key, "name": record["fields"]["name"], "created": created, "passages_added": added,
                "passages": record["fields"]["passages"]}

    def _finish(self, key: str) -> int:
        """Cut the passages from the source's kept text and store them with the finished source, in one
        transaction. Returns how many passages were new."""
        source = self.store.get_record(SOURCE, key)
        text = self.store.record_body(SOURCE, key).decode("utf-8")
        have = {r["key"] for r in self.store.find_records(PASSAGE, source=key)}
        items, added = [], 0
        spans = paragraphs(text)
        for ordinal, (start, end) in enumerate(spans):
            pkey = passage_key(key, ordinal)
            added += pkey not in have
            items.append({"kind": PASSAGE, "key": pkey, "index": ["source"],
                          "fields": {"source": key, "ordinal": ordinal, "start": start, "end": end,
                                     "sha256": sha256(text[start:end])}})
        stored = sha256(text)
        # A record's body belongs to a version, so the finished version carries the kept text again. The engine's
        # archive is content-addressed: the same text is the same object, stored once.
        items.append({"kind": SOURCE, "key": key, "index": ["name", "status"], "body": text,
                      "fields": dict(source["fields"], stored_sha256=stored, redacted=stored != key,
                                     passages=len(spans), status="ingested", ingested_at=time.time())})
        self.store.put_records(items)
        kept = self.store.record_body(SOURCE, key)
        if kept is None or sha256(kept) != stored:
            raise SourceError(f"source {source['fields']['name']}: the store changed its text on the second write")
        return added

    # ------------------------------------------------------------ the index (derived from the records)
    def sync(self) -> int:
        """Bring the index in line with the store: finish interrupted ingests, index every source it lacks, and
        drop sources the store no longer has. Returns how many sources were indexed."""
        indexed = 0
        current = set()
        for record in self.store.records(SOURCE):
            if record["fields"]["status"] != "ingested":
                self._finish(record["key"])
                record = self.store.get_record(SOURCE, record["key"])
            current.add(record["key"])
            indexed += self._index(record)
        conn = self._connect()
        try:
            stale = [k for (k,) in conn.execute("SELECT key FROM sources") if k not in current]
            with conn:
                for k in stale:
                    self._drop(conn, k)
        finally:
            conn.close()
        return indexed

    @staticmethod
    def _drop(conn: sqlite3.Connection, key: str) -> None:
        rows = conn.execute("SELECT rowid, text FROM passages WHERE source = ?", (key,)).fetchall()
        conn.executemany("INSERT INTO passage_fts(passage_fts, rowid, text) VALUES ('delete', ?, ?)", rows)
        conn.execute("DELETE FROM passages WHERE source = ?", (key,))
        conn.execute("DELETE FROM sources WHERE key = ?", (key,))

    def _index(self, record: dict) -> bool:
        """Index one finished source, unless it already is. Every passage is checked against its hash."""
        key, fields = record["key"], record["fields"]
        conn = self._connect()
        try:
            if conn.execute("SELECT 1 FROM sources WHERE key = ?", (key,)).fetchone():
                return False
            text = self.store.record_body(SOURCE, key).decode("utf-8")
            if sha256(text) != fields["stored_sha256"]:
                raise SourceError(f"source {fields['name']}: its kept text doesn't match its hash")
            rows = sorted((r["fields"] for r in self.store.find_records(PASSAGE, source=key)),
                          key=lambda f: f["ordinal"])
            if len(rows) != fields["passages"]:
                raise SourceError(f"source {fields['name']}: {len(rows)} passages stored, {fields['passages']} expected")
            with conn:
                conn.execute("INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (key, fields["name"], fields["sha256"], fields["stored_sha256"], int(fields["redacted"]),
                              fields["size"], fields["passages"], fields["ingested_at"]))
                for p in rows:
                    passage = text[p["start"]:p["end"]]
                    if sha256(passage) != p["sha256"]:
                        raise SourceError(f"source {fields['name']}, passage {p['ordinal']}: text doesn't match "
                                          "its hash")
                    cur = conn.execute('INSERT INTO passages (key, source, ordinal, start, "end", sha256, text) '
                                       "VALUES (?, ?, ?, ?, ?, ?, ?)",
                                       (passage_key(key, p["ordinal"]), key, p["ordinal"], p["start"], p["end"],
                                        p["sha256"], passage))
                    conn.execute("INSERT INTO passage_fts(rowid, text) VALUES (?, ?)", (cur.lastrowid, passage))
            return True
        finally:
            conn.close()

    # ------------------------------------------------------------ reading
    def search_passages(self, query: str, limit: int = 5) -> list[Passage]:
        """Passages matching any word of the query, best first (FTS5 BM25). Words are matched as words, so the
        query's punctuation and FTS5 syntax have no effect."""
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        words = _WORD.findall(query)
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        conn = self._connect()
        try:
            rows = conn.execute(
                'SELECT p.key, p.source, s.name, p.ordinal, p.start, p."end", p.sha256, p.text, bm25(passage_fts) '
                "FROM passage_fts JOIN passages p ON p.rowid = passage_fts.rowid JOIN sources s ON s.key = p.source "
                "WHERE passage_fts MATCH ? ORDER BY bm25(passage_fts) LIMIT ?", (match, limit)).fetchall()
        finally:
            conn.close()
        return [Passage(*row[:8], score=round(-row[8], 6)) for row in rows]

    def passages(self, source: str) -> list[Passage]:
        """A source's passages, in order."""
        conn = self._connect()
        try:
            rows = conn.execute('SELECT p.key, p.source, s.name, p.ordinal, p.start, p."end", p.sha256, p.text '
                                "FROM passages p JOIN sources s ON s.key = p.source WHERE p.source = ? "
                                "ORDER BY p.ordinal", (source,)).fetchall()
        finally:
            conn.close()
        return [Passage(*row) for row in rows]

    def sources(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT key, name, sha256, stored_sha256, redacted, size, passages, ingested_at "
                                "FROM sources ORDER BY ingested_at").fetchall()
        finally:
            conn.close()
        names = ("key", "name", "sha256", "stored_sha256", "redacted", "size", "passages", "ingested_at")
        return [dict(zip(names, r), redacted=bool(r[4])) for r in rows]

    def source_text(self, source: str) -> str | None:
        """A source's kept text, from the store."""
        body = self.store.record_body(SOURCE, source)
        return body.decode("utf-8") if body is not None else None


def passages_path_for(db_path: str | Path) -> Path:
    """The passage index beside a store: adam_memory.db -> adam_memory.passages.db."""
    return Path(db_path).with_suffix(".passages.db")


def open_library(db_path: str | None = None, backend: str | None = None,
                 workspace: str | Path | None = None) -> SourceLibrary:
    """The library on ADAM's store (ADAM_DB, default adam_memory.db; the engine store unless ADAM_STORE says)."""
    from memory.system import open_store
    db = db_path or os.environ.get("ADAM_DB", "adam_memory.db")
    return SourceLibrary(open_store(db, backend), passages_path_for(db), workspace)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m memory.source_library",
                                     description="ADAM's source library: ingest Markdown, search passages.")
    parser.add_argument("--db", help="the store (default: ADAM_DB, or adam_memory.db)")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="add a Markdown file, once")
    ingest.add_argument("file")
    ingest.add_argument("--workspace", help="only files inside this folder can be ingested "
                                            "(default: ADAM_WORKSPACE, or the current folder)")
    search = sub.add_parser("search", help="find passages (FTS5, BM25)")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    sub.add_parser("list", help="list the sources")
    args = parser.parse_args(argv)
    try:
        library = open_library(args.db, workspace=getattr(args, "workspace", None))
        if args.command == "ingest":
            result = library.ingest(args.file)
            if result["created"] or result["passages_added"]:
                print(f"ingested {result['name']}: {result['passages_added']} passages added "
                      f"({result['passages']} in all), source {result['source'][:12]}")
            else:
                print(f"{result['name']} is already in the library ({result['passages']} passages); nothing added")
        elif args.command == "search":
            for p in library.search_passages(args.query, args.limit):
                print(json.dumps({k: v for k, v in asdict(p).items()}, ensure_ascii=False))
        else:
            for s in library.sources():
                print(f"{s['name']}\t{s['passages']} passages\t{s['sha256'][:12]}" + ("\tredacted" if s["redacted"] else ""))
    except (SourceError, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
