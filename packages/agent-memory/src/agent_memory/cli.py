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

**Storage (Stage 2.11):**
- `amem storage report|compress|decompress`
- `amem purge --value-stdin|--object ID|--session S [--rotate-key] --reason ...`: user only, never an agent tool
- `amem export backup.tar.gz [--include-key]`
- `amem import backup.tar.gz`
- `amem verify [--full]`: by default, from the newest valid checkpoint on
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
                 "declare": "mem_declare", "storage": "mem_storage"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="amem", description="Lossless Tree Memory Engine")
    parser.add_argument("--project", default=".", help="project root (default: current directory)")
    parser.add_argument("--home", help="put the store under this directory instead of <project>/.agent-memory "
                                       "(AMEM_HOME does the same)")
    parser.add_argument("--session", default=os.environ.get("AMEM_SESSION", CLI_SESSION),
                        help="the working session for tools and context (default: AMEM_SESSION or amem-cli)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("where", help="print where this project's store lives")
    ver = sub.add_parser("verify", help="check the database, chains, objects, references, checkpoints, structure and "
                                        "derived layer; reports, never repairs")
    ver.add_argument("--full", action="store_true",
                     help="re-check the whole history (default: from the newest valid checkpoint on)")
    pur = sub.add_parser("purge", help="remove content for good (a leaked secret, an object, or a session); the "
                                       "purge is recorded without the content")
    what = pur.add_mutually_exclusive_group(required=True)
    what.add_argument("--value-stdin", action="store_true", help="read the value to purge from stdin")
    what.add_argument("--object", help="an archive object id")
    what.add_argument("--session", dest="purge_session", help="a session id: all its content")
    pur.add_argument("--reason", default="", help="why (recorded)")
    pur.add_argument("--rotate-key", action="store_true", help="also re-encrypt everything under a new data key")
    exp = sub.add_parser("export", help="write a consistent backup (tar.gz) of the store")
    exp.add_argument("out", help="the backup file to write")
    exp.add_argument("--include-key", action="store_true",
                     help="include the key file (anyone with the backup can then read it)")
    imp = sub.add_parser("import", help="unpack a backup into this project's (empty) store folder")
    imp.add_argument("backup", help="the backup file to read")
    rec = sub.add_parser("reconcile", help="record every file change since the last reconcile")
    rec.add_argument("--full", action="store_true", help="rehash every file instead of asking git what changed")
    sub.add_parser("checkpoint", help="take a checkpoint now")
    sub.add_parser("recover", help="rebuild state from the newest valid checkpoint, replay, and reconcile")
    sub.add_parser("rebuild", help="regenerate the derived layer (artifact and search indexes) from the core")
    sub.add_parser("mcp", help="serve the agent tools over stdio (Model Context Protocol); --session auto follows "
                              "the agent session the hooks started")
    hk = sub.add_parser("hook", help="run one agent hook: the agent's JSON on stdin, its hook output on stdout "
                                     "(always exits 0)")
    hk.add_argument("agent", choices=["claude-code"])
    hk.add_argument("event")
    from agent_memory import tools
    for command, tool in TOOL_COMMANDS.items():
        p = sub.add_parser(command, help=tools.TOOLS[tool]["description"])
        if tools.TOOLS[tool]["ops"]:
            p.add_argument("op", choices=tools.TOOLS[tool]["ops"])
        p.add_argument("pairs", nargs="*", metavar="key=value")
    args = parser.parse_args(argv)

    if args.command == "hook":   # before opening the store: the adapter handles a broken store itself
        from agent_memory.adapters import run
        environ = dict(os.environ, AMEM_PROJECT=os.path.abspath(args.project) if args.project != "." else
                       os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        if args.home:
            environ["AMEM_HOME"] = args.home
        out, code = run(args.agent, args.event, sys.stdin.buffer.read(), environ)
        if out:
            sys.stdout.write(out)
            sys.stdout.flush()
        return code
    path = store_path(args.project, args.home)
    if args.command == "where":
        print(path)
        return 0
    if args.command == "import":
        from agent_memory.storage import import_backup
        _print(import_backup(args.backup, path))
        return 0
    store = Store(path)
    if args.command == "purge":
        value = sys.stdin.buffer.read().rstrip(b"\r\n") if args.value_stdin else None
        _print(store.purge(value=value, object_id=args.object, session_id=args.purge_session, reason=args.reason,
                           rotate_key=args.rotate_key))
        return 0
    if args.command == "export":
        _print(store.export(args.out, include_key=args.include_key))
        return 0
    if args.command == "mcp":
        from agent_memory.mcp import serve
        serve(store, args.session)   # "auto": the session the agent's hooks most recently started
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
        report = store.verify(full=args.full)
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
