"""Ledger storage: one JSON object per line, appended, never rewritten."""
import json
from pathlib import Path

LEDGER = Path.home() / ".tally" / "ledger.jsonl"


def ledger_path() -> Path:
    return LEDGER


def append(entry: dict, path: Path | None = None) -> None:
    p = path or ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def load(path: Path | None = None) -> list[dict]:
    p = path or ledger_path()
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
