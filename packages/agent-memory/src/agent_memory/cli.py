"""`amem`: the engine's command line.

Stage 2.2 shipped `where` and `verify`. Stage 2.5 adds `reconcile`,
`checkpoint`, `recover` and `rebuild` (design 8). The retrieval commands
arrive in Stage 2.6.

Every command prints JSON. `verify` exits 1 when it finds a problem, and it
never repairs anything.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from agent_memory.location import store_path
from agent_memory.store import Store

CLI_SESSION = "amem-cli"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="amem", description="Lossless Tree Memory Engine")
    parser.add_argument("--project", default=".", help="project root (default: current directory)")
    parser.add_argument("--home", help="put the store under this directory instead of <project>/.agent-memory "
                                       "(AMEM_HOME does the same)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("where", help="print where this project's store lives")
    sub.add_parser("verify", help="check the database, chains, objects, references, checkpoints, structure and "
                                  "derived layer; reports, never repairs")
    rec = sub.add_parser("reconcile", help="record every file change since the last reconcile")
    rec.add_argument("--full", action="store_true", help="rehash every file instead of asking git what changed")
    sub.add_parser("checkpoint", help="take a checkpoint now")
    sub.add_parser("recover", help="rebuild state from the newest valid checkpoint, replay, and reconcile")
    sub.add_parser("rebuild", help="regenerate the derived layer (the code graph) from the core")
    args = parser.parse_args(argv)

    path = store_path(args.project, args.home)
    if args.command == "where":
        print(path)
        return 0
    store = Store(path)
    if args.command == "verify":
        report = store.verify()
        _print(report)
        return 0 if report["ok"] else 1
    if args.command == "reconcile":
        result = store.reconciler(args.project, CLI_SESSION).run(full=args.full)
        _print({"ok": True, "changes": len(result.changes), "hashed": result.hashed, "full": result.full,
                "by_attribution": dict(Counter(c.attribution for c in result.changes)),
                "conflicts": result.conflicts, "group": result.group_event})
        return 0
    if args.command == "checkpoint":
        _print({"checkpoint_id": store.checkpoint(reason="amem checkpoint")})
        return 0
    if args.command == "recover":
        _print(store.recover(args.project, CLI_SESSION))
        return 0
    _print(store.rebuild_derived())
    return 0


def _print(value) -> None:
    print(json.dumps(value, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(main())
