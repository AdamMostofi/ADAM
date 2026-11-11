"""Benchmark the inference engine (Stage 1.2, #28).

Usage:
    .venv/bin/python scripts/bench_kernel.py --out report.json
    .venv/bin/python scripts/bench_kernel.py --compare <git-rev>   # also time that revision's kernel

Each case is timed in a fresh process, so caches and memory don't carry over.
`--compare` extracts the kernel package of a revision into a temporary
directory with `git archive` and runs the same cases against it.

Results and the reasoning: docs/design/kernel-rules.md (Performance).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CASES = {
    # The worst case recorded in #28: a chain of "is" facts, saturated.
    "is chain 40": "[F(f'n{i}', 'is', f'n{i+1}') for i in range(40)]",
    "is chain 80": "[F(f'n{i}', 'is', f'n{i+1}') for i in range(80)]",
    "is chain 160": "[F(f'n{i}', 'is', f'n{i+1}') for i in range(160)]",
    "implies chain 50": "[F('x', 'is', 'c0')] + [F(f'c{i}', 'implies', f'c{i+1}') for i in range(50)]",
    "taxonomy 10x10": "[F(f'k{i}_{j}', 'is', f'k{i}') for i in range(10) for j in range(10)]"
                      " + [F(f'k{i}', 'implies', 'animal') for i in range(10)]",
    "proposition chain 30": "[F('p0', 'is', 'true')] + [F(f'p{i}', 'implies', f'p{i+1}') for i in range(30)]",
    "equality web 15": "[F(f'e{i}', 'equals', f'e{i+1}') for i in range(15)] + [F('e0', 'is', 'red')]",
}

RUNNER = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from kernel.engine import InferenceEngine
from kernel.facts import Fact
F = lambda s, p, o: Fact(s, p, o)
facts = eval(sys.argv[2])
mode = sys.argv[3]
engine = InferenceEngine()
start = time.perf_counter()
if mode == "batch":
    engine.add_facts(facts)
    engine.infer(max_iterations=10**9)
else:
    for f in facts:
        engine.add_fact(f)
        engine.infer(max_iterations=10**9)
print(json.dumps({"seconds": round(time.perf_counter() - start, 4), "beliefs": len(engine.beliefs)}))
'''


def run(kernel_root: str, case: str, mode: str, timeout: int) -> dict:
    try:
        out = subprocess.run([sys.executable, "-c", RUNNER, kernel_root, CASES[case], mode],
                             capture_output=True, text=True, timeout=timeout, check=True)
        return json.loads(out.stdout)
    except subprocess.TimeoutExpired:
        return {"seconds": None, "timeout": timeout}


def extract(rev: str, into: str) -> str:
    blob = subprocess.run(["git", "-C", ROOT, "archive", rev, "kernel"], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        tar.extractall(into, filter="data") if sys.version_info >= (3, 12) else tar.extractall(into)
    return into


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", help="write the report as JSON here")
    parser.add_argument("--compare", help="git revision whose kernel to time as well")
    parser.add_argument("--timeout", type=int, default=600, help="seconds per case (default 600)")
    args = parser.parse_args()

    kernels = {"current": ROOT}
    tmp = None
    if args.compare:
        tmp = tempfile.TemporaryDirectory()
        kernels[args.compare] = extract(args.compare, tmp.name)

    report = {"python": platform.python_version(), "machine": platform.machine(), "cases": {}}
    for case in CASES:
        report["cases"][case] = {}
        for name, root in kernels.items():
            for mode in ("batch", "one at a time"):
                result = run(root, case, mode, args.timeout)
                report["cases"][case][f"{name}, {mode}"] = result
                print(f"{case:22} {name:12} {mode:14} {result}", flush=True)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)
    if tmp:
        tmp.cleanup()


if __name__ == "__main__":
    main()
