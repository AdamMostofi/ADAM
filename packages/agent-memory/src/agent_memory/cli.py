"""`amem`: the engine's command line.

**Maintenance:** `where`, `verify`, `reconcile`, `checkpoint`, `recover`, `rebuild`. These print JSON.
`verify` exits 1 when it finds a problem, and it never repairs anything.

**Agent tools** (Stage 2.10): the same tools an agent gets over MCP, with the
same context accounting. Each is `amem <tool> [op] [key=value ...]`. Values
are read as JSON when they parse, otherwise as text.

```bash
amem knowledge topics
amem knowledge find kind=bug status=open
amem artifacts find_part name=refresh
amem state overview
amem load id=bug:...
amem offload handle=c3 keep="fixed by a lock"
amem context assemble prompt="refresh fails in prod"
amem declare create kind=task title="add rotation"
```

The working session comes from `--session` (or `AMEM_SESSION`, default
`amem-cli`).

**`amem mcp`** serves the tools to an agent over stdio (MCP).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

from agent_memory.location import store_path
from agent_memory.store import Store

CLI_SESSION = "amem-cli"
TOOL_COMMANDS = {"state": "mem_state", "knowledge": "mem_knowledge", "artifacts": "mem_artifacts",
                 "history": "mem_history", "links": "mem_links", "get": "mem_get", "load": "mem_load",
                 "offload": "mem_offload", "restore": "mem_restore", "pin": "mem_pin", "context": "mem_context",
                 "declare": "mem_declare"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="amem", description="Lossless Tree Memory Engine")
    parser.add_argument("--project", default=".", help="project root (default: current directory)")
    parser.add_argument("--home", help="put the store under this directory instead of <project>/.agent-memory "
                                       "(AMEM_HOME does the same)")
    parser.add_argument("--session", default=os.environ.get("AMEM_SESSION", CLI_SESSION),
                        help="the working session for tools and context (default: AMEM_SESSION or amem-cli)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("where", help="print where this project's store lives")
    sub.add_parser("verify", help="check the database, chains, objects, references, checkpoints, structure and "
                                  "derived layer; reports, never repairs")
    rec = sub.add_parser("reconcile", help="record every file change since the last reconcile")
    rec.add_argument("--full", action="store_true", help="rehash every file instead of asking git what changed")
    sub.add_parser("checkpoint", help="take a checkpoint now")
    sub.add_parser("recover", help="rebuild state from the newest valid checkpoint, replay, and reconcile")
    sub.add_parser("rebuild", help="regenerate the derived layer (artifact and search indexes) from the core")
    sub.add_parser("mcp", help="serve the agent tools over stdio (Model Context Protocol)")
    from agent_memory import tools
    for command, tool in TOOL_COMMANDS.items():
        p = sub.add_parser(command, help=tools.TOOLS[tool]["description"])
        if tools.TOOLS[tool]["ops"]:
            p.add_argument("op", choices=tools.TOOLS[tool]["ops"])
        p.add_argument("pairs", nargs="*", metavar="key=value")
    args = parser.parse_args(argv)

    path = store_path(args.project, args.home)
    if args.command == "where":
        print(path)
        return 0
    store = Store(path)
    if args.command == "mcp":
        from agent_memory.mcp import serve
        serve(store, args.session)
        return 0
    if args.command in TOOL_COMMANDS:
        from agent_memory.context import ContextError
        values = {}
        for pair in args.pairs:
            key, sep, value = pair.partition("=")
            if not sep:
                print(f"expected key=value, got {pair!r}", file=sys.stderr)
                return 2
            try:
                values[key] = json.loads(value)
            except json.JSONDecodeError:
                values[key] = value
        if getattr(args, "op", None):
            values["op"] = args.op
        try:
            print(tools.call(store, args.session, TOOL_COMMANDS[args.command], values))
        except (ContextError, ValueError, KeyError, TypeError) as err:
            print(f"{type(err).__name__}: {err}", file=sys.stderr)
            return 1
        return 0
    if args.command == "verify":
        report = store.verify()
        _print(report)
        return 0 if report["ok"] else 1
    if args.command == "reconcile":
        result = store.reconciler(args.project, args.session).run(full=args.full)
        _print({"ok": True, "changes": len(result.changes), "hashed": result.hashed, "full": result.full,
                "by_attribution": dict(Counter(c.attribution for c in result.changes)),
                "conflicts": result.conflicts, "group": result.group_event})
        return 0
    if args.command == "checkpoint":
        _print({"checkpoint_id": store.checkpoint(reason="amem checkpoint")})
        return 0
    if args.command == "recover":
        _print(store.recover(args.project, args.session))
        return 0
    _print(store.rebuild_derived())
    return 0


def _print(value) -> None:
    print(json.dumps(value, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(main())
