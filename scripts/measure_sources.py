"""Measure the source library on a book-sized Markdown file (Stage 4.2, #24).

Usage:
    .venv/bin/python scripts/measure_sources.py [--paragraphs 5000] [--out report.json]

In a fresh temporary folder (its own key folder too), it writes a generated Markdown book, then times: the
first ingest, a second ingest of the same file, passage search, and rebuilding the passage index from the
records. It also reports the process's peak RSS and the size on disk. No model is loaded.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_XDG = tempfile.mkdtemp(prefix="adam-measure-sources-")
for _name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
    os.environ[_name] = os.path.join(_XDG, _name.lower())

from memory.engine_store import EngineStore  # noqa: E402
from memory.source_library import SourceLibrary  # noqa: E402

WORDS = ("socrates plato athens virtue knowledge justice soul courage wisdom city law death life truth "
         "question answer friend teacher student court jury god oracle examined unexamined living worth").split()


def book(n: int, seed: int = 7) -> str:
    rng = random.Random(seed)
    parts = []
    for i in range(n):
        if i % 25 == 0:
            parts.append(f"## Chapter {i // 25 + 1}")
        sentences = [" ".join(rng.choice(WORDS) for _ in range(rng.randint(6, 16))).capitalize() + "."
                     for _ in range(rng.randint(1, 4))]
        parts.append(" ".join(sentences))
    return "\n\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--paragraphs", type=int, default=5000)
    parser.add_argument("--out")
    args = parser.parse_args()
    folder = Path(tempfile.mkdtemp(prefix="adam-sources-"))
    (folder / "book.md").write_text(book(args.paragraphs), encoding="utf-8")
    store = EngineStore(folder / "facts.engine")
    library = SourceLibrary(store, folder / "facts.passages.db", folder)

    start = time.perf_counter()
    first = library.ingest("book.md")
    ingest = time.perf_counter() - start
    start = time.perf_counter()
    second = library.ingest("book.md")
    again = time.perf_counter() - start

    queries = [" ".join(random.Random(i).sample(WORDS, 3)) for i in range(100)]
    times = []
    for q in queries:
        s = time.perf_counter()
        library.search_passages(q, limit=5)
        times.append(time.perf_counter() - s)

    (folder / "facts.passages.db").unlink()
    start = time.perf_counter()
    SourceLibrary(EngineStore(folder / "facts.engine"), folder / "facts.passages.db", folder)
    rebuild = time.perf_counter() - start

    def size(path: Path) -> int:
        return path.stat().st_size if path.is_file() else sum(p.stat().st_size for p in path.rglob("*") if p.is_file())

    report = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source_bytes": (folder / "book.md").stat().st_size, "passages": first["passages"],
        "ingest_seconds": round(ingest, 3), "second_ingest_seconds": round(again, 4),
        "second_ingest_added": second["passages_added"],
        "search_ms": {"median": round(statistics.median(times) * 1000, 3),
                      "p95": round(sorted(times)[94] * 1000, 3)},
        "index_rebuild_seconds": round(rebuild, 3),
        "engine_store_mb": round(size(folder / "facts.engine") / 1e6, 2),
        "passage_index_mb": round(size(folder / "facts.passages.db") / 1e6, 2),
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "models_loaded": sorted(m for m in sys.modules if m.split(".")[0] in ("onnxruntime", "lancedb", "fastembed")),
    }
    print(json.dumps(report, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
