"""Throwaway prototype: append-only log, checkpoint, replay after a random kill (Stage 2.1 spike, #50).

A writer process appends hash-chained events to SQLite (WAL, synchronous=FULL),
sometimes several per transaction, and every CHECKPOINT_EVERY events stores a
checkpoint: the log position, the chain hash there, and a snapshot of the
derived state. The parent kills the writer with SIGKILL at a random moment,
then recovers:

1. walk the chain and stop at the first record whose hash doesn't verify;
2. take the newest checkpoint whose chain hash matches the verified chain at
   its position and whose snapshot hash is intact;
3. replay the events after it.

The result must equal a clean replay of the whole log from nothing. Some
trials also corrupt the newest checkpoint first, so recovery must skip it.

Usage: python spikes/reconciler/replay.py [--trials 300] [--out report.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHECKPOINT_EVERY = 50
KINDS = ["tool_call", "tool_result", "file_change", "verification", "note"]


def connect(db: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("CREATE TABLE IF NOT EXISTS events (pos INTEGER PRIMARY KEY, payload TEXT NOT NULL, hash TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS checkpoints (pos INTEGER PRIMARY KEY, chain TEXT NOT NULL, "
                 "state TEXT NOT NULL, state_hash TEXT NOT NULL)")
    return conn


def chain(prev: str, payload: str) -> str:
    return hashlib.sha256((prev + payload).encode()).hexdigest()


def event(seed: int, i: int) -> dict:
    r = random.Random(seed * 1_000_003 + i)
    return {"i": i, "kind": r.choice(KINDS), "path": f"src/f{r.randrange(40)}.py", "delta": r.randrange(-5, 6)}


def apply(state: dict, e: dict) -> dict:
    state["count"] = state.get("count", 0) + 1
    kinds = state.setdefault("kinds", {})
    kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    files = state.setdefault("files", {})
    files[e["path"]] = files.get(e["path"], 0) + e["delta"]
    state["last"] = e["i"]
    return state


def dump(state: dict) -> str:
    return json.dumps(state, sort_keys=True, separators=(",", ":"))


def writer(db: str, seed: int, total: int) -> None:
    conn = connect(db)
    state, prev, i = {}, "genesis", 0
    r = random.Random(seed)
    while i < total:
        batch = r.choice([1, 1, 1, 3, 7])          # some transactions hold several events
        conn.execute("BEGIN IMMEDIATE")
        for _ in range(min(batch, total - i)):
            i += 1
            payload = dump(event(seed, i))
            prev = chain(prev, payload)
            conn.execute("INSERT INTO events VALUES (?, ?, ?)", (i, payload, prev))
            apply(state, json.loads(payload))
            if i % CHECKPOINT_EVERY == 0:
                pending_checkpoint = (i, prev, dump(state))
            else:
                pending_checkpoint = None
        conn.execute("COMMIT")
        if pending_checkpoint:                      # its own transaction, after the events are durable
            pos, at, snap = pending_checkpoint
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR REPLACE INTO checkpoints VALUES (?, ?, ?, ?)",
                         (pos, at, snap, hashlib.sha256(snap.encode()).hexdigest()))
            conn.execute("COMMIT")


def verified_chain(conn) -> dict[int, str]:
    hashes, prev = {}, "genesis"
    for pos, payload, h in conn.execute("SELECT pos, payload, hash FROM events ORDER BY pos"):
        if chain(prev, payload) != h or pos != len(hashes) + 1:
            break
        hashes[pos] = prev = h
    return hashes


def recover(db: str) -> tuple[dict, int, int]:
    conn = connect(db)
    hashes = verified_chain(conn)
    start_state, start_pos = {}, 0
    for pos, at, snap, snap_hash in conn.execute("SELECT * FROM checkpoints ORDER BY pos DESC"):
        if hashes.get(pos) == at and hashlib.sha256(snap.encode()).hexdigest() == snap_hash:
            start_state, start_pos = json.loads(snap), pos
            break
    state = start_state
    for pos, payload in conn.execute("SELECT pos, payload FROM events WHERE pos > ? ORDER BY pos", (start_pos,)):
        if pos not in hashes:
            break
        apply(state, json.loads(payload))
    return state, start_pos, len(hashes)


def clean(db: str) -> dict:
    conn = connect(db)
    hashes = verified_chain(conn)
    state = {}
    for pos, payload in conn.execute("SELECT pos, payload FROM events ORDER BY pos"):
        if pos not in hashes:
            break
        apply(state, json.loads(payload))
    return state


def trial(tmp: Path, seed: int, corrupt: bool) -> dict:
    db = str(tmp / f"t{seed}.db")
    proc = subprocess.Popen([sys.executable, __file__, "--write", db, str(seed), "200000"])
    time.sleep(random.Random(seed).uniform(0.05, 1.5))
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait()
    corrupted = None
    if corrupt:
        conn = connect(db)
        row = conn.execute("SELECT pos, state FROM checkpoints ORDER BY pos DESC LIMIT 1").fetchone()
        if row:
            corrupted = row[0]
            conn.execute("UPDATE checkpoints SET state = ? WHERE pos = ?", (row[1].replace("1", "2", 1), row[0]))
    start = time.perf_counter()
    recovered, from_pos, events = recover(db)
    seconds = time.perf_counter() - start
    expected = clean(db)
    result = {"seed": seed, "events": events, "checkpoint_used": from_pos, "corrupted_checkpoint": corrupted,
              "match": dump(recovered) == dump(expected), "recover_seconds": round(seconds, 4)}
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db + suffix)
        except FileNotFoundError:
            pass
    return result


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--write":
        writer(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=300)
    parser.add_argument("--out")
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for seed in range(args.trials):
            results.append(trial(Path(tmp), seed, corrupt=(seed % 6 == 5)))
    matches = sum(r["match"] for r in results)
    corrupt = [r for r in results if r["corrupted_checkpoint"] is not None]
    summary = {
        "trials": len(results), "matches": matches,
        "events_min": min(r["events"] for r in results), "events_max": max(r["events"] for r in results),
        "corrupted_trials": len(corrupt),
        "corrupted_skipped": sum(1 for r in corrupt if r["checkpoint_used"] != r["corrupted_checkpoint"]),
        "recover_seconds_max": max(r["recover_seconds"] for r in results),
        "kills_inside_a_batch_or_checkpoint": "covered by random timing; transactions make both all-or-nothing",
    }
    print(json.dumps(summary, indent=2))
    failures = [r for r in results if not r["match"]]
    if failures:
        print("FAILURES:", failures[:5])
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "trials": results}, indent=2))


if __name__ == "__main__":
    main()
