"""`amem`: the engine's command line. Stage 2.2 ships `where` and `verify`; the rest arrives in Stage 2.6."""
from __future__ import annotations

import argparse
import json
import sys

from agent_memory.location import store_path
from agent_memory.store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="amem", description="Lossless Tree Memory Engine")
    parser.add_argument("--project", default=".", help="project root (default: current directory)")
    parser.add_argument("--home", help="store base directory (default: AMEM_HOME or the user data directory)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("where", help="print where this project's store lives")
    sub.add_parser("verify", help="check hash chains and archived objects; reports, never repairs")
    args = parser.parse_args(argv)
    path = store_path(args.project, args.home)
    if args.command == "where":
        print(path)
        return 0
    report = Store(path).verify()
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
