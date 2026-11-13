"""Run the seeded scenarios through the prototype reconciler and score it (Stage 2.1 spike, #50).

Usage: python spikes/reconciler/run_attribution.py [--large N] [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "packages" / "agent-memory" / "tests" / "fixtures" / "reconcile"))

from reconciler import Reconciler  # noqa: E402
import scenarios  # noqa: E402


def score_scenarios(root: Path, mode: str) -> dict:
    steps = []
    reconciler = None
    totals = {"expected": 0, "detected": 0, "exact": 0, "acceptable": 0, "wrong": 0,
              "spurious": 0, "fast_path_misses": 0, "conflicts_expected": 0, "conflicts_found": 0}
    for step, repo in scenarios.run_scenario(root):
        if reconciler is None:
            # Built after the first step's files exist would hide it; build on the initial commit instead.
            reconciler = Reconciler.__new__(Reconciler)
            reconciler.repo = repo
            reconciler.mode = mode
            reconciler.dirty = set()
            subprocess_state(reconciler, repo)
            reconciler.dirty = set()
        start = time.perf_counter()
        result = reconciler.reconcile(step.observations, full=False)
        fast_missed = []
        if step.full_scan:
            found = {(c.path, c.kind) for c in result.changes}
            fast_missed = [e.path for e in step.expected if (e.path, e.kind) not in found]
            if fast_missed:
                # The design's periodic full hash: re-scan everything by content.
                result = reconciler.reconcile(step.observations, full=True)
        elapsed = time.perf_counter() - start
        got = {(c.path, c.kind): c for c in result.changes}
        record = {"step": step.name, "seconds": round(elapsed, 4), "expected": len(step.expected),
                  "fast_path_missed": fast_missed, "misses": [], "wrong": [], "acceptable": [], "spurious": [],
                  "groups": len(result.groups), "conflicts": len(result.conflicts)}
        for e in step.expected:
            totals["expected"] += 1
            c = got.pop((e.path, e.kind), None)
            if c is None:
                record["misses"].append(e.path)
                continue
            totals["detected"] += 1
            if c.attribution == e.attribution and (e.old_path is None or c.old_path == e.old_path):
                totals["exact"] += 1
            elif c.attribution in e.acceptable:
                totals["acceptable"] += 1
                record["acceptable"].append(f"{e.path}: {c.attribution} (truth {e.attribution})")
            else:
                totals["wrong"] += 1
                record["wrong"].append(f"{e.path}: {c.attribution} (truth {e.attribution})")
        for (path, kind), c in got.items():
            totals["spurious"] += 1
            record["spurious"].append(f"{path} {kind} {c.attribution}")
        totals["fast_path_misses"] += len(fast_missed)
        totals["conflicts_expected"] += step.conflicts
        totals["conflicts_found"] += len(result.conflicts)
        steps.append(record)
    return {"totals": totals, "steps": steps}


def subprocess_state(reconciler: Reconciler, repo: Path) -> None:
    """Initialise the reconciler on the repository's committed state (before the first scenario step)."""
    import subprocess
    reconciler.head = reconciler._head()
    reconciler.reflog = reconciler._reflog()
    reconciler.snapshot = {}
    snapshot, _ = reconciler._scan(full=True)
    # Undo the first step's edits in the baseline: use the committed blobs.
    for rel in list(snapshot):
        blob = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{rel}"], capture_output=True)
        if blob.returncode == 0:
            import hashlib
            size, mtime, _ = snapshot[rel]
            snapshot[rel] = (len(blob.stdout), -1, hashlib.sha256(blob.stdout).hexdigest())
        else:
            del snapshot[rel]   # not committed yet: created by the first step
    reconciler.snapshot = snapshot


def time_large(root: Path, files: int, mode: str) -> dict:
    start = time.perf_counter()
    repo = scenarios.make_large_repo(root, files)
    build = time.perf_counter() - start
    out = {"files": files, "build_seconds": round(build, 2)}
    start = time.perf_counter()
    rec = Reconciler(repo, mode=mode)
    out["cold_full_scan_seconds"] = round(time.perf_counter() - start, 3)
    start = time.perf_counter()
    r = rec.reconcile([{"type": "session_start", "writer": "a"}])
    out["warm_scan_no_changes_seconds"] = round(time.perf_counter() - start, 3)
    out["warm_hashed"] = r.hashed
    for i in range(10):
        (repo / "pkg" / f"mod_{i:03d}.py").write_text(f"changed = {i}\n")
    start = time.perf_counter()
    r = rec.reconcile([{"type": "session_start", "writer": "a"}])
    out["warm_scan_10_changes_seconds"] = round(time.perf_counter() - start, 3)
    out["detected"] = len(r.changes)
    start = time.perf_counter()
    rec.reconcile([{"type": "session_start", "writer": "a"}], full=True)
    out["full_rehash_seconds"] = round(time.perf_counter() - start, 3)
    import subprocess
    start = time.perf_counter()
    subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, check=True)
    out["git_status_seconds"] = round(time.perf_counter() - start, 3)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--large", type=int, default=20_000)
    parser.add_argument("--out")
    args = parser.parse_args()
    report = {}
    for mode in ("walk", "git_status"):
        r = report[mode] = {}
        with tempfile.TemporaryDirectory() as tmp:
            r["scenarios"] = score_scenarios(Path(tmp) / "small", mode)
        with tempfile.TemporaryDirectory() as tmp:
            r["small_repo"] = time_large(Path(tmp), 40, mode)
        with tempfile.TemporaryDirectory() as tmp:
            r["large_repo"] = time_large(Path(tmp), args.large, mode)
        print(f"===== mode {mode}")
        print(json.dumps(r["scenarios"]["totals"]))
        for s in r["scenarios"]["steps"]:
            flags = {k: s[k] for k in ("misses", "wrong", "acceptable", "spurious", "fast_path_missed") if s[k]}
            if flags:
                print(f"  {s['step']:38} {flags}")
        print("small repo:", r["small_repo"])
        print("large repo:", r["large_repo"])
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
