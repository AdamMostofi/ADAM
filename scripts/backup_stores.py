"""Copy ADAM's runtime stores into a dated backup folder and verify the copy.

Usage:
    python scripts/backup_stores.py [--dest backups/<date>] [--root .]

The stores are copied byte for byte with timestamps preserved. Every file is
hashed in the source and in the copy, and the run fails unless they match.
A manifest is written next to the copy. The source stores are only read.
Stop any running ADAM process first, so the copy is consistent.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import sys

STORES = ("adam_memory.db", "adam_vectors.lance", "adam_save")


def file_hashes(path: str) -> dict[str, dict]:
    """Return {relative path: {sha256, size}} for a file or every file under a folder."""
    files = [path] if os.path.isfile(path) else [
        os.path.join(d, f) for d, _, names in os.walk(path) for f in names
    ]
    result = {}
    for f in sorted(files):
        digest = hashlib.sha256()
        with open(f, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        rel = os.path.relpath(f, os.path.dirname(path))
        result[rel] = {"sha256": digest.hexdigest(), "size": os.path.getsize(f)}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="ADAM repository root")
    parser.add_argument("--dest", help="backup folder (default: backups/<today>)")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    dest = os.path.abspath(args.dest or os.path.join(root, "backups", dt.date.today().isoformat()))
    missing = [s for s in STORES if not os.path.exists(os.path.join(root, s))]
    if missing:
        print(f"missing stores: {missing}", file=sys.stderr)
        return 1
    for store in STORES:
        if os.path.exists(os.path.join(dest, store)):
            print(f"refusing to overwrite existing backup: {os.path.join(dest, store)}", file=sys.stderr)
            return 1

    needed = sum(v["size"] for s in STORES for v in file_hashes(os.path.join(root, s)).values())
    free = shutil.disk_usage(os.path.dirname(dest) if os.path.exists(os.path.dirname(dest)) else root).free
    if free < needed * 1.1:
        print(f"not enough space: need about {needed:,} bytes, {free:,} free", file=sys.stderr)
        return 1

    os.makedirs(dest, exist_ok=True)
    manifest = {"created": dt.datetime.now().isoformat(timespec="seconds"), "source": root, "stores": {}}
    for store in STORES:
        src, dst = os.path.join(root, store), os.path.join(dest, store)
        before = file_hashes(src)
        if os.path.isdir(src):
            shutil.copytree(src, dst, copy_function=shutil.copy2)
        else:
            shutil.copy2(src, dst)
        after_src, copied = file_hashes(src), file_hashes(dst)
        if before != after_src:
            print(f"{store} changed during the copy; stop ADAM and retry", file=sys.stderr)
            return 1
        if copied != before:
            print(f"{store} copy does not match the source", file=sys.stderr)
            return 1
        manifest["stores"][store] = {"files": len(before), "bytes": sum(v["size"] for v in before.values()), "hashes": before}
        print(f"copied {store}: {len(before)} files, {manifest['stores'][store]['bytes']:,} bytes, hashes match")

    for db in ("adam_memory.db", os.path.join("adam_save", "memory.db")):
        path = os.path.join(dest, db)
        with sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True) as conn:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        manifest.setdefault("sqlite_integrity", {})[db] = check
        print(f"integrity_check {db}: {check}")
        if check != "ok":
            return 1

    with open(os.path.join(dest, "MANIFEST.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=1)
    print(f"backup complete: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
