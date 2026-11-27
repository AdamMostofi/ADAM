"""Measure what EQ changes that a user sees, after Stage 4.3 (Stage 4.4, #77).

Usage:
    .venv/bin/python scripts/measure_eq.py [--samples 8] [--no-mouth] [--out report.json]

It plays the chat session in tests/data/eq_session.json through ADAMCore, in a temporary folder, with the
Socrates facts and one source, and reports:
1. **Routes:** how each turn was answered, and on which turns EQ's parameters reach the Mouth at all (since
   Stage 4.3, only chatter goes to the Mouth).
2. **Changes:** how often appraisal makes the parameters differ from neutral, over all turns and over the
   turns that reach the Mouth.
3. **The visible effect through the Mouth** (with the real TinyChat15M, unless --no-mouth): for each Mouth turn,
   `--samples` replies with EQ's parameters and as many with neutral ones, and how many of each pass the
   claim check and are shown.
4. **The CLI's tone label** (`ADAM [negative]`, its border colour): how often it matches the session's labels.
5. **Accuracy as it stands:** the held-out probes (eq_probe.json and eq_probe_4_4.json), scored as is.
6. **Cost:** EQ's time per turn, and the SQLite file it writes on every turn.
The embedding model is replaced by a fake; no store of the user's is opened.
"""
from __future__ import annotations

import argparse
import collections
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

from interface.evidence import model_text_is_grounded  # noqa: E402
from learning.eq.adjuster import ResponseParams  # noqa: E402
from learning.eq.engine import EQEngine  # noqa: E402
from memory.semantic_index import SemanticIndex  # noqa: E402

SemanticIndex._load_model = lambda self: None
SemanticIndex._embed = lambda self, text: [0.0] * 383 + [1.0]

FACTS = [("socrates", "instance_of", "man"), ("man", "subclass_of", "mortal"), ("mortal", "subclass_of", "animal"),
         ("plato", "instance_of", "man"), ("rock", "not_instance_of", "animal"), ("tweety", "instance_of", "bird"),
         ("bird", "typically", "flier")]
DATA = ROOT / "tests" / "data"


class RecordingMouth:
    """Records the parameters each Mouth call gets; replies with nothing (the claim check then drops it)."""

    def __init__(self):
        self.calls = []

    def format_response(self, message, params, context=""):
        self.calls.append((message, dict(params)))
        return ""


def neutral_params() -> dict:
    p = ResponseParams()
    return {"warmth": p.warmth, "depth": p.depth, "tone": "neutral"}


def accuracy(path: Path) -> dict:
    data = json.loads(path.read_text())
    misses = [i["text"] for i in data["items"]
              if EQEngine(":memory:").process_input(i["text"])[0].emotional_tone.value != i["tone"]]
    out = {"correct": len(data["items"]) - len(misses), "total": len(data["items"]), "misses": misses}
    if "sequences" in data:
        seq = []
        for s in data["sequences"]:
            eq = EQEngine(":memory:")
            last = [eq.process_input(t)[0] for t in s["turns"]][-1]
            seq.append({"turns": s["turns"], "expected": s["last_tone"], "read": last.emotional_tone.value})
        out["sequences"] = seq
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--no-mouth", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()
    from interface.core import ADAMCore

    folder = Path(tempfile.mkdtemp(prefix="adam-eq-"))
    mouth = RecordingMouth()
    core = ADAMCore(db_path=str(folder / "adam_memory.db"), lance_path=str(folder / "adam_vectors.db"), mouth=mouth)
    for f in FACTS:
        core.add_fact(*f)
    (folder / "ws").mkdir()
    (folder / "ws" / "apology.md").write_text("# Apology\n\nThe unexamined life is not worth living, said Socrates.\n")
    library = core.memory.source_library()
    library.workspace = (folder / "ws").resolve()
    library.ingest("apology.md")

    turns = json.loads((DATA / "eq_session.json").read_text())["turns"]
    rows, eq_times = [], []
    timing = EQEngine(":memory:")       # a separate engine, so timing doesn't change the session's own state
    for turn in turns:
        before = len(mouth.calls)
        start = time.perf_counter()
        timing.process_input(turn["text"])
        eq_times.append(time.perf_counter() - start)
        result = core.chat(turn["text"])
        appraised = {"warmth": result["params"]["warmth"], "depth": result["params"]["depth"],
                     "tone": result["state"]["emotional_tone"]}
        rows.append({"text": turn["text"], "label": turn["tone"], "answer_source": result["answer_source"],
                     "reaches_mouth": len(mouth.calls) > before, "params": appraised,
                     "params_differ_from_neutral": appraised != neutral_params(),
                     "cli_tone": result["state"]["emotional_tone"]})

    sources = collections.Counter(r["answer_source"] for r in rows)
    mouth_rows = [r for r in rows if r["reaches_mouth"]]
    report = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "turns": len(rows),
        "answer_sources": dict(sources),
        "turns_reaching_the_mouth": len(mouth_rows),
        "params_differ_from_neutral": {"all_turns": sum(r["params_differ_from_neutral"] for r in rows),
                                       "mouth_turns": sum(r["params_differ_from_neutral"] for r in mouth_rows)},
        "cli_tone_label_matches": sum(r["cli_tone"] == r["label"] for r in rows),
        "eq_appraise_ms_median": round(statistics.median(eq_times) * 1000, 3),
        "sqlite_written_by_eq": (folder / "adam_memory.db").exists(),
        "probes": {"eq_probe.json": accuracy(DATA / "eq_probe.json"),
                   "eq_probe_4_4.json": accuracy(DATA / "eq_probe_4_4.json")},
        "rows": rows,
    }

    if not args.no_mouth:
        from interface.mouth import Mouth
        real = Mouth(server_bin=os.environ.get("ADAM_LLAMA_SERVER", str(Path.home() / ".local/bin/llama-server")),
                     port=8095)
        effect = []
        try:
            for r in mouth_rows:
                counts = {}
                for label, params in (("eq", r["params"]), ("neutral", neutral_params())):
                    shown = [t for t in (real.format_response(r["text"], params) for _ in range(args.samples))
                             if model_text_is_grounded(t, r["text"])]
                    counts[label] = {"shown": len(shown), "of": args.samples, "examples": shown[:3]}
                effect.append({"text": r["text"], "params": r["params"], **counts})
        finally:
            real.close()
        report["mouth_effect"] = effect

    text = json.dumps(report, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
