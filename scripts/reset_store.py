"""Back up and reset ADAM's runtime stores to a fresh, empty state.

Usage:
    python scripts/reset_store.py            # show what would happen; changes nothing
    python scripts/reset_store.py --yes      # back up, delete, and recreate the stores

Steps:
1. Refuse if an ADAM process is running.
2. Make sure a verified backup exists: reuse an existing backups/*/MANIFEST.json
   whose file hashes match the current stores exactly, otherwise make a new
   backup with scripts/backup_stores.py. Skipped only when the stores are
   already fresh and empty, since there is nothing to lose.
3. Delete adam_memory.db, adam_vectors.db, the old adam_vectors.lance folder,
   adam_save/ and skills/.
4. Create an empty fact store (schema version 1, meta table) and an empty
   vector index (model and dimension recorded in its meta table). No
   placeholder rows.

Running it again on fresh stores changes nothing (idempotent).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import shutil
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

import backup_stores  # noqa: E402

FACTS_DB = "adam_memory.db"
VECTORS_DB = "adam_vectors.db"
DELETE = (FACTS_DB, VECTORS_DB, "adam_vectors.lance", "adam_save", "skills")
SQLITE_SIDECARS = ("-journal", "-wal", "-shm")


def adam_processes() -> list[str]:
    """Command lines of running ADAM web or CLI processes (Linux /proc)."""
    found = []
    for pid in os.listdir("/proc") if os.path.isdir("/proc") else []:
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                cmd = handle.read().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if "interface.web.app" in cmd or "interface.cli" in cmd:
            found.append(f"{pid}: {cmd.strip()}")
    return found


def is_fresh(root: str) -> bool:
    """True when the stores are exactly a fresh reset: no facts, no vectors, nothing else."""
    if any(os.path.exists(os.path.join(root, s)) for s in ("adam_vectors.lance", "adam_save", "skills")):
        return False
    facts, vectors = os.path.join(root, FACTS_DB), os.path.join(root, VECTORS_DB)
    if not (os.path.isfile(facts) and os.path.isfile(vectors)):
        return False
    try:
        with sqlite3.connect(f"file:{facts}?mode=ro", uri=True) as conn:
            if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
                return False
            if conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] != 0:
                return False
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "eq_state" in tables and conn.execute("SELECT COUNT(*) FROM eq_state").fetchone()[0] != 0:
                return False
        with sqlite3.connect(f"file:{vectors}?mode=ro", uri=True) as conn:
            if conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] != 0:
                return False
    except sqlite3.Error:
        return False
    return True


def matching_backup(root: str) -> str | None:
    """An existing backup whose manifest matches the current stores file for file."""
    current = backup_stores.current_hashes(root)
    if not current:
        return None
    for manifest_path in sorted(glob.glob(os.path.join(root, "backups", "*", "MANIFEST.json"))):
        try:
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.load(handle)
        except (OSError, ValueError):
            continue
        recorded = {}
        for store in manifest.get("stores", {}).values():
            recorded.update(store.get("hashes", {}))
        if recorded == current:
            return os.path.dirname(manifest_path)
    return None


def remove(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)


def create_fresh(root: str) -> dict:
    from memory.exact_store import ExactStore
    from memory.semantic_index import SemanticIndex

    facts = ExactStore(os.path.join(root, FACTS_DB))
    index = SemanticIndex(os.path.join(root, VECTORS_DB))
    summary = {
        "facts": facts.count(),
        "facts_meta": facts.meta(),
        "vectors": index.count(),
        "vectors_meta": index.meta(),
        "facts_bytes": os.path.getsize(os.path.join(root, FACTS_DB)),
        "vectors_bytes": os.path.getsize(os.path.join(root, VECTORS_DB)),
    }
    index.close()
    return summary


def reset(root: str, yes: bool) -> int:
    root = os.path.abspath(root)
    running = adam_processes()
    if running:
        print("ADAM is running; stop it first:\n  " + "\n  ".join(running), file=sys.stderr)
        return 1

    present = [s for s in DELETE if os.path.exists(os.path.join(root, s))]
    if is_fresh(root):
        print("stores are already fresh and empty; nothing to do")
        return 0

    reuse = matching_backup(root)
    plan = [f"reuse verified backup {reuse}" if reuse else "make a new verified backup",
            f"delete: {', '.join(present) or 'nothing'}",
            f"create empty {FACTS_DB} and {VECTORS_DB}"]
    if not yes:
        print("Dry run. With --yes this would:\n  " + "\n  ".join(plan))
        return 2

    if reuse:
        print(f"current stores match the backup in {reuse}; reusing it")
    elif present:
        dest = os.path.join(root, "backups", dt.datetime.now().strftime("%Y-%m-%d-%H%M%S"))
        if backup_stores.backup(root, dest) != 0:
            print("backup failed; nothing was deleted", file=sys.stderr)
            return 1

    for name in present:
        remove(os.path.join(root, name))
        for suffix in SQLITE_SIDECARS:
            remove(os.path.join(root, name + suffix))
        print(f"deleted {name}")

    summary = create_fresh(root)
    print("fresh stores:", json.dumps(summary, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=REPO, help="folder holding the stores (default: the repo)")
    parser.add_argument("--yes", action="store_true", help="actually back up, delete and recreate")
    args = parser.parse_args()
    return reset(args.root, args.yes)


if __name__ == "__main__":
    sys.exit(main())
