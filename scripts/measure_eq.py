"""Score EQ tone on the labelled set (Stage 1.7, #37).

Usage:
    .venv/bin/python scripts/measure_eq.py [--out report.json] [--kernel-root DIR]

Runs each labelled sentence through EQEngine.process_input (manual override,
then appraisal) on a fresh engine, and reports accuracy overall and per
label, plus every miss. --kernel-root scores another checkout's code (for a
before/after comparison).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETS = {name: os.path.join(HERE, "tests", "data", f"eq_{name}.json") for name in ("labelled", "probe")}


def score(root: str, path: str) -> dict:
    sys.path.insert(0, root)
    from learning.eq.engine import EQEngine

    with open(path) as f:
        items = json.load(f)["items"]
    per_label: dict[str, list[int]] = {}
    misses = []
    for item in items:
        tone = EQEngine(":memory:").process_input(item["text"])[0].emotional_tone.value
        hit = tone == item["tone"]
        per_label.setdefault(item["tone"], [0, 0])
        per_label[item["tone"]][0] += hit
        per_label[item["tone"]][1] += 1
        if not hit:
            misses.append({"text": item["text"], "expected": item["tone"], "got": tone})
    correct = sum(c for c, _ in per_label.values())
    return {
        "items": len(items), "correct": correct, "accuracy": round(correct / len(items), 3),
        "per_label": {k: {"correct": c, "total": t, "accuracy": round(c / t, 3)} for k, (c, t) in per_label.items()},
        "misses": misses,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out")
    parser.add_argument("--kernel-root", default=HERE)
    args = parser.parse_args()
    report = {name: score(args.kernel_root, path) for name, path in SETS.items()}
    for name, result in report.items():
        print(f"{name}: {result['correct']}/{result['items']} ({result['accuracy']:.1%})")
        for miss in result["misses"]:
            print(f"  miss: {miss['text']!r}: expected {miss['expected']}, got {miss['got']}")
    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
