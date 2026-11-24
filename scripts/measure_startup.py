"""Measure how long ADAM takes to rebuild its engine and graph at startup (Stage 1.6, #36; stores, Stage 4.1).

Usage:
    .venv/bin/python scripts/measure_startup.py --out report.json [--sizes 1000 5000 20000] [--store engine]

Each size builds a fresh temporary store of given facts: individuals that
are instances of 50 leaf classes in a 3-level class hierarchy, so restoring
also runs real inference. The embedding model is not loaded: restore()
reads facts and rebuilds the engine and graph, it doesn't embed anything.

`--store` picks the store: `engine` (the default, the Yewtree engine) or `exact` (the original SQLite store).
The engine store keeps its key in a temporary config folder, never the user's.
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
_XDG = tempfile.mkdtemp(prefix="adam-measure-startup-")
for _name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
    os.environ[_name] = os.path.join(_XDG, _name.lower())

from kernel.facts import Fact  # noqa: E402
from memory.semantic_index import SemanticIndex  # noqa: E402
from memory.system import BACKENDS, MemorySystem, open_store  # noqa: E402

SemanticIndex._load_model = lambda self: None  # restore() never embeds


def build(path: str, n: int, backend: str) -> None:
    store = open_store(path, backend)
    facts = [Fact(f"leaf{i}", "subclass_of", f"mid{i % 10}") for i in range(50)]
    facts += [Fact(f"mid{i}", "subclass_of", f"top{i % 3}") for i in range(10)]
    facts += [Fact(f"thing{i}", "instance_of", f"leaf{i % 50}") for i in range(n)]
    for f in facts:
        store.upsert(f)
    store.close()


def measure(n: int, backend: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "facts.db")
        build(db, n, backend)
        start = time.perf_counter()
        memory = MemorySystem(db_path=db, lance_path=os.path.join(tmp, "vectors.db"), backend=backend)
        total = time.perf_counter() - start
        return {"store": backend, "given_facts": n + 60, "seconds": round(total, 3), **memory.startup,
                "graph_edges": len(memory.graph_edges())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 5000, 20000])
    parser.add_argument("--store", choices=BACKENDS, default="engine")
    parser.add_argument("--out")
    args = parser.parse_args()
    report = {"python": platform.python_version(), "machine": platform.machine(), "runs": []}
    for n in args.sizes:
        result = measure(n, args.store)
        report["runs"].append(result)
        print(json.dumps(result), flush=True)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
