# agent-memory

**Status:** Phase 2 is complete (Stages 2.1 to 2.11) inside the ADAM
repository. Phase 3 has started: the [Claude Code plugin](../../plugins/claude-code/README.md) (Stage 3.1). `agent-memory` is a working name; the final name is decision D8.

The Lossless Tree Memory Engine is a general-purpose, lossless memory for
long-running AI agents, with software development as its primary use.

**The principle:** the entire history is kept permanently, but an agent loads
only what it needs, from the right tree, at the right time.

Design documents:
- [architecture revision 3](../../docs/design/2026-11-13-memory-architecture-rev3.md), the current architecture;
- the [original design](../../docs/design/2026-11-06-agent-memory-engine.md).

This package never imports ADAM. A test enforces it, and CI runs its tests in
an environment where ADAM isn't installed.

## The four trees

One shared store holds four independently navigable trees. Links between
them are explicit, and each link says which trees it joins.

| Tree | Navigator | Answers | Holds |
|---|---|---|---|
| History | `store.history` | What happened? | Sessions, turns and events, in order; conversation search |
| Artifacts | `store.artifacts` | What exists? | Folders and artifacts with every version; symbols, sections, dependencies, metadata, search |
| Knowledge | `store.knowledge` | What do we know? | Topics holding decisions, approaches, requirements, constraints, concepts, explanations, discoveries, bugs, solutions, questions, references |
| Active State | `store.state` | What matters now? | Ten sections of declared and generated items, with staleness and token-budgeted levels |

**Every record and link has a basis:**
- `observed`: the engine saw it;
- `declared`: an agent or the user stated it;
- `inferred`: the engine derived it, and the rule is named.

## What works so far

- **Capture and storage (Stages 2.2, 2.5):**
  - a canonical event format, and an append-only event log with per-writer hash chains;
  - a compressed, encrypted, content-addressed archive;
  - secret redaction and path exclusions, both recorded;
  - gap records instead of silent loss, and capture that fails open (`safe_append`).
- **Where it lives (decision D3):** inside the project, in `.agent-memory/`, which ignores itself in git. `AMEM_HOME` overrides it.
- **Structure (Stages 2.3, 2.6):**
  - the four trees, with per-tree schemas checked on every write;
  - cross-tree links, typed relationships and development paths;
  - domain profiles: `generic`, `software` and `documents`;
  - format upgrades by replaying the log, which is never changed.
- **Artifacts (Stages 2.4, 2.7):**
  - file versions, with rename and revert detection;
  - Python and TypeScript imports (tsconfig aliases included) and symbols;
  - Markdown and reStructuredText sections and links;
  - metadata for any file, and full-text search;
  - test results shown as verified, stale or unknown, with reasons.
- **Knowledge (Stage 2.8):**
  - entry kinds with statuses, and a topic hierarchy;
  - supersession chains;
  - bug-to-solution-to-evidence links;
  - knowledge and conversation search.
- **Active state (Stage 2.9):**
  - objectives, progress, tasks, blockers, priorities, constraints, open conflicts, working context, verification and next actions;
  - generated items, such as changes since the last session and decisions that apply to the current focus;
  - staleness with reasons;
  - levels 0 to 2 within budgets you can set (`store.configure`);
  - never any raw tool output.
- **Reconciliation and recovery (Stage 2.5):**
  - attribution of file changes to `agent_tool`, `agent_bash`, `git_operation`, `external` or an honest `unattributed`;
  - conflict records for concurrent agents;
  - checkpoints, and crash recovery that matches a clean replay;
  - `amem verify`, which reports four things separately (#93). Archive integrity (its exit code) proves the captured records are intact and continuous, not that nothing was missed before capture. So it also reports capture completeness within the instrumentation (sessions that ended cleanly, the last reconciliation), known gaps (`capture_gap` and `partial` records) and uncertain attribution (`unattributed` changes).

```python
from agent_memory import Store
store = Store(".agent-memory")                       # or use location.store_path(project_root)
bug = store.declare_entry("bug", "refresh race", "s1", "agent", topic="auth", concerns=["src/auth/jwt.py"])
store.declare_state("task", "fix the refresh race", "s1", "agent")
store.knowledge.topics()                             # browse: listings only, no bodies
store.artifacts.find_part("refresh")                 # where is it defined?
store.state.overview()                               # level 0: what matters now, in about 200 tokens
start = store.context.assemble("s2", prompt="why does refresh fail?")   # the session's starting context
packet = store.context.load("s2", bug, level=2)      # then load, offload, restore by handle
store.context.offload("s2", packet["handle"], keep="caused by a double rotate")
```

```bash
cd packages/agent-memory
uv sync --locked --extra dev
uv run pytest -q
uv run amem --project /path/to/project reconcile    # also: where, verify, checkpoint, recover, rebuild
```

- **The context manager (Stage 2.10):**
  - a crash-safe ledger of what the agent has loaded, with token budgets per tree;
  - protected items (constraints, objectives, open conflicts, active work, pins) that are never evicted automatically;
  - offloading to one-line references, with exact restore;
  - offers for what a prompt names but the context lacks;
  - recovery after compaction;
  - delivery for clients that build every request (`request_context`) or add context per prompt (`delta`).
- **Agent tools:** `mem_state`, `mem_knowledge`, `mem_artifacts`, `mem_history`, `mem_links`, `mem_get`, `mem_load`, `mem_context` (including offload, restore and pin), `mem_storage`, `mem_declare`. They are served over MCP (`amem mcp`) and the CLI (`amem knowledge topics`, `amem offload handle=c3 keep=...`).

- **Storage (Stage 2.11):**
  - **Compression:** old, unvisited content is packed and compressed losslessly (lzma) once the store passes a recommended size, or whenever an agent or user asks (`mem_storage`, `amem storage compress|decompress`).
  - **Purge** of a leaked secret, an object or a session leaves no byte behind, keeps history connected, and can rotate the data key (`amem purge`; user only).
  - **Size and growth reporting,** with warnings.
  - **Backups:** `amem export` / `amem import`.
  - **Faster checks:** batch appends (a 20,000-file first scan in about 10 s), and a fast `amem verify` from the newest checkpoint (`--full` for everything).

- **Agent adapters (Stage 3.1):** `amem hook claude-code <Event>` and the Claude Code plugin, with:
  - lossless capture that never blocks the agent;
  - memory injected at session start, on each prompt and after compaction;
  - key storage chosen at onboarding: key file, passphrase with a session cache, or OS keychain.

## Not built yet
- **Phase 3:** the agent plugins and onboarding.

Known problems are tracked as [follow-up issues](https://github.com/AdamMostofi/ADAM/issues?q=is%3Aissue+is%3Aopen+label%3Afollow-up).
