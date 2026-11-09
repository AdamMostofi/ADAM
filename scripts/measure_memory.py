"""Measure ADAM's memory in each state and check it against the budget.

Usage:
    python scripts/measure_memory.py [--budget-mb 400] [--out report.json] [--facts 200]

Every measurement runs in a fresh process with temporary stores, so the
production stores are never opened. The run starts the real Ear (Needle),
the real embedding model, and the Mouth's llama-server, so they must be
installed; set FASTEMBED_CACHE_PATH and ADAM_LLAMA_SERVER as needed.

States (definition in docs/design/memory-budget.md):
- startup: ADAM is running and ready, before any request
- chat:    after chat turns that use memory and the Mouth, including llama-server
- ingest:  after storing many facts in one process (study work; recorded, not enforced)
- peak:    the highest total seen during the run

Exit codes: 0 within budget, 1 over budget, 2 measurement failed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ENFORCED_STATES = ("startup", "chat")

# Runs inside a fresh interpreter; prints one JSON object per step.
LIFECYCLE = r"""
import json, os, sys, time
sys.path.insert(0, {repo!r})
sys.path.insert(0, {here!r})
import memory_probe as mp

steps = []
peak = 0.0
def mark(name, **extra):
    global peak
    tree = mp.tree_memory()
    peak = max(peak, tree.total_rss_mb)
    steps.append({{"step": name, **tree.as_dict(), **extra}})

mark("python_started")
import numpy, networkx, lancedb, flask
mark("libraries_imported")
from interface.core import ADAMCore
mark("adam_imported")
t = time.time()
core = ADAMCore(db_path={db!r}, lance_path={lance!r})
mark("startup", seconds=round(time.time() - t, 2))

t = time.time()
core.add_fact("socrates", "is", "man")
core.add_fact("man", "implies", "mortal")
mark("first_facts_stored", seconds=round(time.time() - t, 2))

t = time.time()
turns = ["what do you know about socrates", "is socrates mortal", "tell me about men"]
replies = [core.chat(m, mode="full")["response"] for m in turns]
mark("chat", seconds=round(time.time() - t, 2), turns=len(turns), first_reply=replies[0][:60])

t = time.time()
for i in range({facts}):
    core.add_fact(f"item{{i}}", "is", f"kind{{i % 17}}")
mark("ingest", seconds=round(time.time() - t, 2), facts={facts})

time.sleep(2)
mark("after_ingest_idle")
core.mouth.close()
print(json.dumps({{"steps": steps, "peak_total_rss_mb": round(peak, 1)}}))
"""

ISOLATED = {
    "ear_only": "from interface.ear import Ear\nobj = Ear()\nobj.listen('hello there')",
    "embedding_only": (
        "from fastembed import TextEmbedding\n"
        "obj = TextEmbedding(model_name='sentence-transformers/all-MiniLM-L6-v2')\n"
        "list(obj.embed(['socrates is man']))"
    ),
    "lancedb_only": (
        "import lancedb, tempfile\n"
        "db = lancedb.connect(tempfile.mkdtemp())\n"
        "t = db.create_table('t', data=[{'id': 'a', 'vector': [0.0] * 384}])\n"
        "t.search([0.0] * 384).limit(1).to_list()"
    ),
}

ISOLATED_TEMPLATE = r"""
import json, sys
sys.path.insert(0, {repo!r}); sys.path.insert(0, {here!r})
import memory_probe as mp
before = mp.tree_memory().total_rss_mb
{body}
after = mp.tree_memory()
print(json.dumps({{"baseline_mb": round(before, 1), **after.as_dict()}}))
"""


def run_python(code: str, timeout: int = 600) -> dict:
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            timeout=timeout, cwd=tempfile.mkdtemp(prefix="adam-mem-"))
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-2000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--budget-mb", type=float, default=400.0)
    parser.add_argument("--facts", type=int, default=200)
    parser.add_argument("--out", help="write the full report as JSON")
    args = parser.parse_args()

    sys.path.insert(0, HERE)
    import memory_probe as mp

    work = tempfile.mkdtemp(prefix="adam-mem-stores-")
    code = LIFECYCLE.format(repo=REPO, here=HERE, db=os.path.join(work, "m.db"),
                            lance=os.path.join(work, "v.lance"), facts=args.facts)
    try:
        lifecycle = run_python(code)
        isolated = {name: run_python(ISOLATED_TEMPLATE.format(repo=REPO, here=HERE, body=body))
                    for name, body in ISOLATED.items()}
    except Exception as exc:  # noqa: BLE001 - report any measurement failure clearly
        print(f"measurement failed: {exc}", file=sys.stderr)
        return 2

    by_step = {s["step"]: s for s in lifecycle["steps"]}
    states = {
        "startup": by_step["startup"]["total_rss_mb"],
        "chat": by_step["chat"]["total_rss_mb"],
        "ingest": by_step["ingest"]["total_rss_mb"],
        "peak": lifecycle["peak_total_rss_mb"],
    }
    violations = mp.budget_violations(states, args.budget_mb, ENFORCED_STATES)
    report = {
        "budget_mb": args.budget_mb,
        "enforced_states": list(ENFORCED_STATES),
        "states_total_rss_mb": states,
        "lifecycle": lifecycle["steps"],
        "isolated": isolated,
        "python": sys.version.split()[0],
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "violations": violations,
    }
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=1)

    print(f"{'step':<22}{'total RSS':>11}{'total PSS':>11}{'main RSS':>10}  processes")
    for s in lifecycle["steps"]:
        procs = ", ".join(f"{p['name']} {p['rss_mb']}" for p in s["processes"])
        pss = "-" if s["total_pss_mb"] is None else f"{s['total_pss_mb']:.1f}"
        print(f"{s['step']:<22}{s['total_rss_mb']:>11.1f}{pss:>11}{s['main_rss_mb']:>10.1f}  {procs}")
    print("\nisolated components (process total RSS / baseline):")
    for name, r in isolated.items():
        print(f"  {name:<16}{r['total_rss_mb']:>8.1f} MB  (python baseline {r['baseline_mb']} MB)")
    print("\nstates:", {k: round(v, 1) for k, v in states.items()})
    if violations:
        print("OVER BUDGET:\n  " + "\n  ".join(violations))
        return 1
    print(f"within the {args.budget_mb:.0f} MB budget for {', '.join(ENFORCED_STATES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
