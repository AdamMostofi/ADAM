"""The thought trace: what ADAM did on each chat turn, as typed nodes (Stage 4.6, #35, "Trace the Thought").

**A trace is data, not prose.** Each turn records a few typed nodes. Each node has inputs, outputs, a
confidence, its provenance and a timestamp. `render()` writes English from them whenever it is asked; the
English is never stored, so it can never drift from what happened.

**The node types** (DT.1: start small, grow with use; `TRACE_VERSION` says which vocabulary a trace uses):
- `PERCEIVE`: the message, how it was routed (small talk, question, statement, chatter), and the frustration
  reading.
- `RECALL`: what memory recall returned, and what the source library's search found.
- `INFER`: what inference stored this turn, and the proof an answer rests on, linked to the stored facts and
  their derivation records (Stage 1.4, #30) by id.
- `ANSWER`: where the reply came from (`answer_source`), its citations, and the hash of its text.

**Retention** (the owner's call, 2026-11-27): traces are kept per conversation, with no limit on the turns in a
conversation, for the last 5,000 conversations. Older conversations' traces are deleted. A conversation is one
web chat ("New" starts another) or one run of the CLI. The facts and proofs a trace points to live in the
store and are never deleted; only the notes about old conversations go. So traces live in their own small
SQLite file beside the store (`adam_memory.traces.db`): the engine store never deletes.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

TRACE_VERSION = 1
NODE_TYPES = ("PERCEIVE", "RECALL", "INFER", "ANSWER")
KEEP_CONVERSATIONS = 5000
_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, started REAL NOT NULL, last REAL NOT NULL, turns INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS traces (
    id TEXT PRIMARY KEY, conversation TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn INTEGER NOT NULL, created REAL NOT NULL, version INTEGER NOT NULL, nodes TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traces_conversation ON traces(conversation, turn);
CREATE INDEX IF NOT EXISTS idx_conversations_last ON conversations(last);
"""


def node(kind: str, inputs: dict, outputs: dict, confidence: float | None, provenance: list[str]) -> dict:
    """One typed node. `confidence` is None where a step is deterministic and no confidence applies."""
    if kind not in NODE_TYPES:
        raise ValueError(f"node type must be one of {NODE_TYPES}")
    return {"type": kind, "inputs": inputs, "outputs": outputs, "confidence": confidence,
            "provenance": list(provenance), "at": time.time()}


def valid_conversation(conversation_id: str | None) -> bool:
    return isinstance(conversation_id, str) and bool(_SESSION.match(conversation_id))


class TraceLog:
    """Traces, one per turn, grouped by conversation, kept for the last `keep` conversations."""

    def __init__(self, path: str | Path, keep: int = KEEP_CONVERSATIONS):
        self.path = Path(path)
        self.keep = keep
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def record(self, conversation_id: str, nodes: list[dict]) -> str:
        """Store one turn's trace and return its id. A new conversation may push the oldest one out."""
        if not valid_conversation(conversation_id):
            raise ValueError("a conversation id is 1 to 64 letters, digits, '-' or '_'")
        for n in nodes:
            if n.get("type") not in NODE_TYPES:
                raise ValueError(f"node type must be one of {NODE_TYPES}")
        trace_id = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._connect() as conn:
            new = conn.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone() is None
            if new:
                conn.execute("INSERT INTO conversations (id, started, last, turns) VALUES (?, ?, ?, 0)",
                             (conversation_id, now, now))
            conn.execute("UPDATE conversations SET last = ?, turns = turns + 1 WHERE id = ?", (now, conversation_id))
            turn = conn.execute("SELECT turns FROM conversations WHERE id = ?", (conversation_id,)).fetchone()[0]
            conn.execute("INSERT INTO traces (id, conversation, turn, created, version, nodes) VALUES (?, ?, ?, ?, ?, ?)",
                         (trace_id, conversation_id, turn, now, TRACE_VERSION, json.dumps(nodes)))
            if new:
                self._prune(conn)
        return trace_id

    def _prune(self, conn: sqlite3.Connection) -> int:
        """Delete the traces of every conversation but the `keep` most recent ones."""
        old = [r[0] for r in conn.execute("SELECT id FROM conversations ORDER BY last DESC, started DESC "
                                          "LIMIT -1 OFFSET ?", (self.keep,))]
        for cid in old:
            conn.execute("DELETE FROM conversations WHERE id = ?", (cid,))   # its traces go with it
        return len(old)

    def get(self, trace_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT id, conversation, turn, created, version, nodes FROM traces WHERE id = ?",
                               (trace_id,)).fetchone()
        if row is None:
            return None
        return {"id": row[0], "conversation": row[1], "turn": row[2], "created": row[3], "version": row[4],
                "nodes": json.loads(row[5])}

    def counts(self) -> dict:
        with self._connect() as conn:
            return {"conversations": conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
                    "traces": conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]}


# ------------------------------------------------------------ English, generated from a trace, never stored
_ROUTES = {"small_talk": "small talk", "question": "a question", "statement": "a statement to check",
           "chatter": "conversation, not a question", "empty": "an empty message"}
_SOURCES = {"proof": "a proof", "passage": "a passage quoted from the source library",
            "no_evidence": "nothing: no evidence backed an answer, so none was given",
            "small_talk": "a fixed small-talk reply", "model": "the Mouth's words, which asserted nothing",
            "acknowledgement": "a plain acknowledgement"}


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def render(trace: dict) -> list[str]:
    """The trace as readable lines, one per node, written from its data."""
    lines = []
    for n in trace["nodes"]:
        i, o = n["inputs"], n["outputs"]
        if n["type"] == "PERCEIVE":
            line = f"Perceived “{i.get('message', '')}” as {_ROUTES.get(o.get('route'), o.get('route'))}."
            if o.get("frustrated"):
                line += " The user seemed frustrated."
            lines.append(line)
        elif n["type"] == "RECALL":
            facts = o.get("facts", [])
            line = f"Recalled {_count(len(facts), 'fact', 'facts')} from memory"
            line += (": " + "; ".join(facts[:5]) + ("; …" if len(facts) > 5 else "") + ".") if facts else "."
            if o.get("library_searched"):
                hits = o.get("passages", [])
                line += (f" Searched the source library: {_count(len(hits), 'passage', 'passages')} cited."
                         if hits else " Searched the source library: no passage answered it.")
            lines.append(line)
        elif n["type"] == "INFER":
            stored = o.get("stored", 0)
            line = (f"Inference stored {_count(stored, 'new conclusion', 'new conclusions')} this turn."
                    if o.get("ran", True) else "Inference didn't run this turn (simple mode).")
            for proof in o.get("proofs", []):
                steps = [s for s in proof["steps"] if s["rule"] != "given"]
                givens = [s["fact"] for s in proof["steps"] if s["rule"] == "given"]
                line += f" Proved “{proof['claim']}” from {_count(len(givens), 'given fact', 'given facts')}"
                if steps:
                    line += " by " + ", then ".join(f"{s['rule']}" for s in steps)
                if proof.get("fact_id") is not None:
                    ids = proof.get("derivation_ids") or []
                    line += f" (fact #{proof['fact_id']}" + (f", derivation record #{', #'.join(map(str, ids))}"
                                                            if ids else ", given") + ")"
                line += "."
            lines.append(line)
        elif n["type"] == "ANSWER":
            line = f"Answered from {_SOURCES.get(o.get('answer_source'), o.get('answer_source'))}."
            for c in o.get("citations", []):
                line += f" Cited {c['name']}, characters {c['start']}–{c['end']}."
            lines.append(line)
    return lines
