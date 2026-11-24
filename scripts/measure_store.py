"""Compare the two stores' latency on ADAM's own workload (Stage 4.1, #46).

Usage:
    .venv/bin/python scripts/measure_store.py [--facts 500] [--out report.json]

For each store (`exact`, the original SQLite store, and `engine`, the Yewtree engine), in a fresh temporary
folder, with the embedding model replaced by a deterministic fake so only storage is timed:
- write:   storing given facts one at a time through MemorySystem.store (graph and vectors included);
- settle:  inferring over a class hierarchy and storing every conclusion with its derivations;
- restart: opening the store and rebuilding the engine and graph (restore);
- reads:   get by id, lookup by subject, text search, and tracing a derived fact back to its inputs.

The engine store keeps its key in a temporary config folder, never the user's.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_XDG = tempfile.mkdtemp(prefix="adam-measure-store-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
    os.environ[name] = os.path.join(_XDG, name.lower())

from kernel.facts import Fact  # noqa: E402
from memory.semantic_index import SemanticIndex  # noqa: E402
from memory.system import MemorySystem  # noqa: E402


def fake_embed(self, text: str) -> list[float]:
    vector = [0.0] * 384
    for word in text.lower().split():
        vector[int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big") % 384] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


SemanticIndex._load_model = lambda self: None
SemanticIndex._embed = fake_embed


def ms(seconds: float) -> float:
    return round(seconds * 1000, 3)


def hierarchy(n_individuals: int) -> list[Fact]:
    """A 3-level class hierarchy (2 roots, 10 mid classes, 50 leaves) and individuals in the leaves."""
    facts = [Fact(f"mid{m}", "subclass_of", f"root{m % 2}") for m in range(10)]
    facts += [Fact(f"leaf{l}", "subclass_of", f"mid{l % 10}") for l in range(50)]
    facts += [Fact(f"thing{i}", "instance_of", f"leaf{i % 50}") for i in range(n_individuals)]
    return facts


def measure(backend: str, n: int) -> dict:
    folder = tempfile.mkdtemp(prefix=f"adam-{backend}-")
    db, vec = os.path.join(folder, "adam_memory.db"), os.path.join(folder, "adam_vectors.db")
    memory = MemorySystem(db_path=db, lance_path=vec, backend=backend)
    facts = hierarchy(n)

    write = []
    for fact in facts:
        start = time.perf_counter()
        memory.store(fact)
        write.append(time.perf_counter() - start)
        memory.engine.add_fact(fact)

    start = time.perf_counter()
    stored = memory.settle(memory.engine, max_iterations=200_000)
    settle = time.perf_counter() - start

    start = time.perf_counter()
    restarted = MemorySystem(db_path=db, lance_path=vec, backend=backend)
    restart = time.perf_counter() - start

    store = restarted.fact_store
    ids = [i for i, _ in store.get_all_with_ids()]
    derived_ids = [i for i, f in store.get_all_with_ids() if f.source.value == "deduced"][:50]

    def timed(fn, items):
        times = []
        for item in items:
            s = time.perf_counter()
            fn(item)
            times.append(time.perf_counter() - s)
        return {"median_ms": ms(statistics.median(times)), "p95_ms": ms(sorted(times)[int(len(times) * 0.95) - 1])}

    reads = {
        "get": timed(store.get, ids[:200]),
        "find_by_subject": timed(store.find_by_subject, [f"thing{i}" for i in range(200)]),
        "search_text": timed(store.search_text, [f"thing{i} " for i in range(50)]),
        "trace": timed(store.trace, derived_ids),
    }
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(folder) for f in fs)
    return {
        "backend": backend, "given_facts": len(facts), "rows_after_settle": store.count(),
        "derived_stored": stored, "derivations": store.count_derivations(),
        "write_per_fact": {"median_ms": ms(statistics.median(write)), "p95_ms": ms(sorted(write)[int(len(write) * 0.95) - 1])},
        "settle_seconds": round(settle, 3), "settle_ms_per_stored_fact": ms(settle / max(stored, 1)),
        "restart_seconds": round(restart, 3), "reads": reads, "disk_mb": round(size / 1e6, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--facts", type=int, default=500, help="individuals in the hierarchy (default 500)")
    parser.add_argument("--out", help="write the report here as JSON")
    args = parser.parse_args()
    report = {"measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "results": [measure(b, args.facts) for b in ("exact", "engine")]}
    for r in report["results"]:
        print(f"{r['backend']:>6}: write {r['write_per_fact']['median_ms']} ms/fact (p95 {r['write_per_fact']['p95_ms']}), "
              f"settle {r['settle_seconds']} s for {r['derived_stored']} conclusions, restart {r['restart_seconds']} s, "
              f"get {r['reads']['get']['median_ms']} ms, by subject {r['reads']['find_by_subject']['median_ms']} ms, "
              f"text {r['reads']['search_text']['median_ms']} ms, trace {r['reads']['trace']['median_ms']} ms, "
              f"disk {r['disk_mb']} MB")
    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
