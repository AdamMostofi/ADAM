"""Measure EQ's one signal, frustration (Stage 4.4, #77).

Usage:
    .venv/bin/python scripts/measure_eq.py [--out report.json]

**The decision run.** The measurement behind the keep/reduce/remove call ran the full EQ through ADAMCore and the
real TinyChat15M; that version of this script is at commit ec2d2d3, and its report is
docs/measurements/2026-11-26-eq-value.json.

This version scores the frustration reader as it is:
- **The probe sets:** the labelled set, the Stage 1.7 held-out probes and the Stage 4.4 held-out probes,
  turn by turn. A turn is right when it reads as troubled exactly when its label is negative.
- **The context sequences** in eq_probe_4_4.json.
- **The chat session** in eq_session.json, through ADAMCore: when the user reads as frustrated, and which
  replies changed because of it.
- **Its time per turn.**

The embedding model is replaced by a fake; no store of the user's is opened.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_XDG = tempfile.mkdtemp(prefix="adam-measure-eq-")
for _name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
    os.environ[_name] = os.path.join(_XDG, _name.lower())

from learning.eq.frustration import FrustrationReader, score  # noqa: E402
from memory.semantic_index import SemanticIndex  # noqa: E402

SemanticIndex._load_model = lambda self: None
SemanticIndex._embed = lambda self, text: [0.0] * 383 + [1.0]

FACTS = [("socrates", "instance_of", "man"), ("man", "subclass_of", "mortal"), ("mortal", "subclass_of", "animal"),
         ("plato", "instance_of", "man"), ("rock", "not_instance_of", "animal"), ("tweety", "instance_of", "bird"),
         ("bird", "typically", "flier")]
DATA = ROOT / "tests" / "data"


class SilentMouth:
    def format_response(self, message, params, context=""):
        return ""


def scored(name: str) -> dict:
    data = json.loads((DATA / name).read_text())
    misses = [{"text": i["text"], "label": i["tone"], "cues": score(i["text"])[1]} for i in data["items"]
              if FrustrationReader().read(i["text"]).troubled != (i["tone"] == "negative")]
    out = {"correct": len(data["items"]) - len(misses), "total": len(data["items"]), "misses": misses}
    if "sequences" in data:
        out["sequences"] = []
        for s in data["sequences"]:
            reader = FrustrationReader()
            last = [reader.read(t) for t in s["turns"]][-1]
            out["sequences"].append({"turns": s["turns"], "expected": s["last_tone"],
                                     "read": "negative" if last.troubled else "not negative",
                                     "right": last.troubled == (s["last_tone"] == "negative")})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out")
    args = parser.parse_args()
    from interface.core import ADAMCore

    folder = Path(tempfile.mkdtemp(prefix="adam-eq-"))
    core = ADAMCore(db_path=str(folder / "adam_memory.db"), lance_path=str(folder / "adam_vectors.db"),
                    mouth=SilentMouth())
    for f in FACTS:
        core.add_fact(*f)
    turns = json.loads((DATA / "eq_session.json").read_text())["turns"]
    session, times = [], []
    timing = FrustrationReader()
    for turn in turns:
        start = time.perf_counter()
        timing.read(turn["text"])
        times.append(time.perf_counter() - start)
        result = core.chat(turn["text"])
        f = result["frustration"]
        session.append({"text": turn["text"], "label": turn["tone"], "troubled": f["troubled"],
                        "frustrated": f["frustrated"], "cues": f["cues"], "answer_source": result["answer_source"],
                        "response": result["response"]})
    report = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "probes": {name: scored(name) for name in ("eq_labelled.json", "eq_probe.json", "eq_probe_4_4.json")},
        "session": {"turns": len(session),
                    "troubled_matches_label": sum(r["troubled"] == (r["label"] == "negative") for r in session),
                    "frustrated_turns": [r["text"] for r in session if r["frustrated"]],
                    "rows": session},
        "read_ms_median": round(statistics.median(times) * 1000, 3),
        "sqlite_written_by_eq": (folder / "adam_memory.db").exists(),
    }
    summary = {k: v for k, v in report.items() if k != "session"}
    summary["session"] = {k: v for k, v in report["session"].items() if k != "rows"}
    print(json.dumps(summary, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
