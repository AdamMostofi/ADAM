"""Read-only audit of ADAM's runtime stores.

Usage:
    python scripts/audit_store.py --out backups/<date>/audit [--root .]

Reports facts, duplicates, sources, EQ rows, skills, vector rows, unique IDs,
the placeholder row, version files, and sizes, and compares them with the
baseline recorded in issue #21.

Read-only guarantees:
- SQLite is opened with `mode=ro&immutable=1`, so no journal or lock file is made.
- LanceDB tables are only read.
- Every file in every store is hashed before and after the audit. The run
  fails if anything changed.
- The only files written are `audit.jsonl` and `audit-summary.md` in --out,
  which must be outside the stores.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys

EXPECTATIONS = {
    # Baseline from #21, confirmed in Stage 0.1 before the reset.
    "baseline-2026-11-09": {
        ("sqlite", "fact_rows"): 16,
        ("sqlite", "unique_spo_tuples"): 1,
        ("sqlite", "eq_rows"): 49,
        ("lance", "rows"): 5401,
        ("lance", "unique_ids"): 1001,
        ("lance", "unique_fact_strings"): 1132,
        ("lance", "placeholder_rows"): 1,
        ("lance", "version_files"): 5402,
        ("adam_save", "bytes"): 45655,
        ("skills", "skill_files"): 0,
    },
    # A store straight after scripts/reset_store.py (Stage 0.6, #23).
    "fresh": {
        ("sqlite", "fact_rows"): 0,
        ("sqlite", "user_version"): 2,
        ("vectors", "rows"): 0,
        ("vectors", "placeholder_rows"): 0,
        ("vectors", "under_10_mb"): True,
        ("skills", "skill_files"): 0,
    },
}
STORE_NAMES = ("adam_memory.db", "adam_vectors.db", "adam_vectors.lance", "adam_save")


def tree_fingerprint(paths: list[str]) -> dict[str, tuple]:
    """Hash, size, and mtime of every file under the given paths."""
    out = {}
    for path in paths:
        files = [path] if os.path.isfile(path) else [
            os.path.join(d, f) for d, _, names in os.walk(path) for f in names
        ]
        for f in sorted(files):
            digest = hashlib.sha256()
            with open(f, "rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
            stat = os.stat(f)
            out[f] = (digest.hexdigest(), stat.st_size, stat.st_mtime_ns)
    return out


def dir_stats(path: str) -> tuple[int, int]:
    files = [os.path.join(d, f) for d, _, names in os.walk(path) for f in names]
    return len(files), sum(os.path.getsize(f) for f in files)


def ro_connect(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def audit_sqlite(path: str, store: str) -> list[dict]:
    rows = []
    with ro_connect(path) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        rows.append(("tables", tables))
        rows.append(("integrity_check", conn.execute("PRAGMA integrity_check").fetchone()[0]))
        rows.append(("user_version", conn.execute("PRAGMA user_version").fetchone()[0]))
        if "facts" in tables:
            rows.append(("fact_rows", conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]))
            rows.append(("unique_spo_tuples", conn.execute(
                "SELECT COUNT(*) FROM (SELECT DISTINCT subject, predicate, object FROM facts)").fetchone()[0]))
            dupes = conn.execute(
                "SELECT subject, predicate, object, COUNT(*) FROM facts "
                "GROUP BY subject, predicate, object HAVING COUNT(*) > 1 ORDER BY COUNT(*) DESC").fetchall()
            rows.append(("duplicate_keys", [{"spo": list(d[:3]), "rows": d[3]} for d in dupes]))
            rows.append(("rows_by_source", dict(conn.execute(
                "SELECT source, COUNT(*) FROM facts GROUP BY source").fetchall())))
            rows.append(("rows_with_proof_chain", conn.execute(
                "SELECT COUNT(*) FROM facts WHERE proof_chain IS NOT NULL").fetchone()[0]))
        if "derivations" in tables:
            rows.append(("derivation_rows", conn.execute("SELECT COUNT(*) FROM derivations").fetchone()[0]))
            rows.append(("derived_without_derivation", conn.execute(
                "SELECT COUNT(*) FROM facts WHERE source = 'deduced' "
                "AND id NOT IN (SELECT conclusion_id FROM derivations)").fetchone()[0]))
        if "eq_state" in tables:
            rows.append(("eq_rows", conn.execute("SELECT COUNT(*) FROM eq_state").fetchone()[0]))
        if "meta" in tables:
            rows.append(("meta", dict(conn.execute("SELECT key, value FROM meta").fetchall())))
    rows.append(("bytes", os.path.getsize(path)))
    return [{"store": store, "check": k, "value": v} for k, v in rows]


def audit_lance(path: str, store: str) -> list[dict]:
    try:
        import lancedb  # only needed for the old LanceDB store
    except ImportError:
        return [{"store": store, "check": "note", "value": "lancedb not installed; old Lance store not read"}]

    out = []
    table_dir = os.path.join(path, "facts.lance")
    for name in ("_versions", "data", "_transactions"):
        sub = os.path.join(table_dir, name)
        count = len(os.listdir(sub)) if os.path.isdir(sub) else 0
        key = {"_versions": "version_files", "data": "data_files", "_transactions": "transaction_files"}[name]
        out.append((key, count))
    files, size = dir_stats(path)
    out += [("files", files), ("bytes", size)]

    table = lancedb.connect(path).open_table("facts")
    data = table.to_arrow().select(["id", "subject", "predicate", "object"]).to_pydict()
    ids = data["id"]
    facts = [f"{s} {p} {o}" for s, p, o in zip(data["subject"], data["predicate"], data["object"])]
    out += [
        ("rows", len(ids)),
        ("unique_ids", len(set(ids))),
        ("unique_fact_strings", len(set(facts))),
        ("placeholder_rows", sum(1 for i in ids if i == "placeholder")),
        ("current_version", table.version),
    ]
    return [{"store": store, "check": k, "value": v} for k, v in out]


def audit_vectors_db(path: str) -> list[dict]:
    """The SQLite vector index introduced in Stage 0.5."""
    with ro_connect(path) as conn:
        rows = conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        placeholder = conn.execute("SELECT COUNT(*) FROM vectors WHERE id = 'placeholder'").fetchone()[0]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall()) if "meta" in tables else {}
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    size = os.path.getsize(path)
    return [{"store": "vectors", "check": k, "value": v} for k, v in (
        ("rows", rows), ("placeholder_rows", placeholder), ("meta", meta), ("integrity_check", integrity),
        ("bytes", size), ("under_10_mb", size < 10_000_000))]


def audit_save(path: str) -> list[dict]:
    files, size = dir_stats(path)
    rows = [{"store": "adam_save", "check": "files", "value": files},
            {"store": "adam_save", "check": "bytes", "value": size}]
    db = os.path.join(path, "memory.db")
    if os.path.exists(db):
        rows += [r for r in audit_sqlite(db, "adam_save/memory.db") if r["check"] != "bytes"]
    graph = os.path.join(path, "graph.json")
    if os.path.exists(graph):
        with open(graph, encoding="utf-8") as handle:
            data = json.load(handle)
        rows.append({"store": "adam_save/graph.json", "check": "nodes_edges",
                     "value": {"nodes": len(data.get("nodes", [])), "edges": len(data.get("edges", []))}})
    lance = os.path.join(path, "vectors.lance")
    if os.path.isdir(os.path.join(lance, "facts.lance")):
        rows += audit_lance(lance, "adam_save/vectors.lance")
    return rows


def audit_skills(root: str) -> list[dict]:
    # learning/engine.py and learning/skill_compiler.py default to skills_dir="skills",
    # relative to the working directory, which is normally the repo root.
    skills_dir = os.path.join(root, "skills")
    count = 0
    if os.path.isdir(skills_dir):
        count = sum(1 for d, _, names in os.walk(skills_dir) for f in names if f.endswith(".json"))
    return [
        {"store": "skills", "check": "configured_location", "value": "skills/ (relative to working directory; default in learning/engine.py)"},
        {"store": "skills", "check": "location_exists", "value": os.path.isdir(skills_dir)},
        {"store": "skills", "check": "skill_files", "value": count},
        {"store": "skills", "check": "note", "value": "agent/skills, .claude/skills and .agents/skills hold coding-agent tooling, not ADAM skills"},
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="folder holding the stores (repo root or a backup folder)")
    parser.add_argument("--out", required=True, help="folder for audit.jsonl and audit-summary.md")
    parser.add_argument("--skills-root", help="where to look for skills/ (default: --root)")
    parser.add_argument("--expect", choices=sorted(EXPECTATIONS), default="baseline-2026-11-09",
                        help="which recorded state to compare against")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    out_dir = os.path.abspath(args.out)
    stores = [os.path.join(root, s) for s in STORE_NAMES if os.path.exists(os.path.join(root, s))]
    if not stores:
        print(f"no stores found in {root}", file=sys.stderr)
        return 1
    for store in stores:
        if os.path.commonpath([out_dir, store]) == store:
            print("--out must be outside the stores", file=sys.stderr)
            return 1

    before = tree_fingerprint(stores)
    records = [{"store": "all", "check": "stores_present", "value": [os.path.basename(s) for s in stores]}]
    for store in stores:
        name = os.path.basename(store)
        if name == "adam_memory.db":
            records += audit_sqlite(store, "adam_memory.db")
        elif name == "adam_vectors.db":
            records += audit_vectors_db(store)
        elif name == "adam_vectors.lance":
            records += audit_lance(store, "adam_vectors.lance")
        else:
            records += audit_save(store)
    records += audit_skills(os.path.abspath(args.skills_root or root))
    after = tree_fingerprint(stores)
    unchanged = before == after

    for r in records:
        key = (r["store"].replace("adam_memory.db", "sqlite").replace("adam_vectors.lance", "lance"), r["check"])
        expected = EXPECTATIONS[args.expect]
        if key in expected:
            r["expected"] = expected[key]
            r["status"] = "match" if r["value"] == expected[key] else "differs"
    records.append({"store": "all", "check": "stores_unchanged_by_audit", "value": unchanged,
                    "files_fingerprinted": len(before)})
    meta = {"store": "all", "check": "audit_run", "value": {
        "root": root, "time": dt.datetime.now().isoformat(timespec="seconds"), "python": sys.version.split()[0]}}

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "audit.jsonl"), "w", encoding="utf-8") as handle:
        for r in [meta] + records:
            handle.write(json.dumps(r, ensure_ascii=False) + "\n")

    lines = [f"# Store audit", "", f"- Root: `{root}`", f"- Time: {meta['value']['time']}",
             f"- Stores unchanged by audit: **{unchanged}** ({len(before)} files fingerprinted)", "",
             "| Store | Check | Value | Expected | Status |", "|---|---|---|---|---|"]
    for r in records:
        value = r["value"]
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
            value = value if len(value) <= 120 else value[:117] + "..."
        lines.append(f"| {r['store']} | {r['check']} | {value} | {r.get('expected', '')} | {r.get('status', '')} |")
    differs = [r for r in records if r.get("status") == "differs"]
    missing = [k for k in EXPECTATIONS[args.expect]
               if not any((r["store"].replace("adam_memory.db", "sqlite").replace("adam_vectors.lance", "lance"), r["check"]) == k
                          for r in records)]
    lines += ["", f"Compared with: {args.expect}", f"Differences: {len(differs)}",
              f"Expected checks not found: {len(missing)}"]
    with open(os.path.join(out_dir, "audit-summary.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    print("\n".join(lines))
    return 0 if unchanged else 2


if __name__ == "__main__":
    sys.exit(main())
