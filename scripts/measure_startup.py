"""Measure how long ADAM takes to rebuild its engine and graph at startup (Stage 1.6, #36).

Usage:
    .venv/bin/python scripts/measure_startup.py --out report.json [--sizes 1000 5000 20000]

Each size builds a fresh temporary store of given facts: individuals that
are instances of 50 leaf classes in a 3-level class hierarchy, so restoring
also runs real inference. The embedding model is not loaded: restore()
reads facts and rebuilds the engine and graph, it doesn't embed anything.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kernel.facts import Fact  # noqa: E402
from memory.exact_store import ExactStore  # noqa: E402
from memory.semantic_index import SemanticIndex  # noqa: E402
from memory.system import MemorySystem  # noqa: E402

SemanticIndex._load_model = lambda self: None  # restore() never embeds


def build(path: str, n: int) -> None:
    store = ExactStore(path)
    facts = [Fact(f"leaf{i}", "subclass_of", f"mid{i % 10}") for i in range(50)]
    facts += [Fact(f"mid{i}", "subclass_of", f"top{i % 3}") for i in range(10)]
    facts += [Fact(f"thing{i}", "instance_of", f"leaf{i % 50}") for i in range(n)]
    for f in facts:
        store.upsert(f)


def measure(n: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "facts.db")
        build(db, n)
        start = time.perf_counter()
        memory = MemorySystem(db_path=db, lance_path=os.path.join(tmp, "vectors.db"))
        total = time.perf_counter() - start
        return {"given_facts": n + 60, "seconds": round(total, 3), **memory.startup,
                "graph_edges": len(memory.graph.get_all_edges())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 5000, 20000])
    parser.add_argument("--out")
    args = parser.parse_args()
    report = {"python": platform.python_version(), "machine": platform.machine(), "runs": []}
    for n in args.sizes:
        result = measure(n)
        report["runs"].append(result)
        print(json.dumps(result), flush=True)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
