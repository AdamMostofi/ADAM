"""Time evidence answers on a large knowledge base (Stage 4.3, #34).

Usage:
    .venv/bin/python scripts/measure_answers.py [--individuals 20000] [--out report.json]

Builds the same taxonomy as scripts/measure_startup.py (individuals in 50 leaf classes under a 3-level
hierarchy) in an inference engine, then times answering each kind of question. No model, no store.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface.evidence import Answerer  # noqa: E402
from interface.mouth import small_talk  # noqa: E402
from kernel.engine import InferenceEngine  # noqa: E402
from kernel.facts import Fact  # noqa: E402

QUESTIONS = {
    "yes/no, derived": "Is thing{i} a top{t}?",
    "yes/no, unknown": "Is thing{i} a leaf{other}?",
    "what is": "What is thing{i}?",
    "statement": "thing{i} is a mid{m}",
    "no evidence": "Who won the 1998 World Cup?",
    "small talk": "how are you?",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--individuals", type=int, default=20000)
    parser.add_argument("--out")
    args = parser.parse_args()
    engine = InferenceEngine()
    for i in range(50):
        engine.add_fact(Fact(f"leaf{i}", "subclass_of", f"mid{i % 10}"))
    for i in range(10):
        engine.add_fact(Fact(f"mid{i}", "subclass_of", f"top{i % 3}"))
    for i in range(args.individuals):
        engine.add_fact(Fact(f"thing{i}", "instance_of", f"leaf{i % 50}"))
    start = time.perf_counter()
    engine.infer(max_iterations=10_000_000)
    infer = time.perf_counter() - start
    answerer = Answerer(engine, small_talk=small_talk)
    report = {"individuals": args.individuals, "beliefs": len(engine.beliefs), "infer_seconds": round(infer, 2),
              "answers": {}}
    for kind, template in QUESTIONS.items():
        times, sources = [], set()
        for n in range(20):
            i = (n * 997) % args.individuals
            leaf = i % 50
            q = template.format(i=i, t=(leaf % 10) % 3, other=(leaf + 1) % 50, m=leaf % 10)
            s = time.perf_counter()
            sources.add(answerer.answer(q).answer_source)
            times.append(time.perf_counter() - s)
        report["answers"][kind] = {"median_ms": round(statistics.median(times) * 1000, 2),
                                   "max_ms": round(max(times) * 1000, 2), "answer_source": sorted(sources)}
    print(json.dumps(report, indent=2))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
