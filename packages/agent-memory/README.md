# agent-memory

**Status:** in development inside the ADAM repository (Phase 2). Stages 2.1 to
2.9 are done; the context manager (2.10) and purge, storage and compression
(2.11) remain. `agent-memory` is a working name; the final name is decision D8.

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
  - `amem verify`.

```python
from agent_memory import Store
store = Store(".agent-memory")                       # or use location.store_path(project_root)
bug = store.declare_entry("bug", "refresh race", "s1", "agent", topic="auth", concerns=["src/auth/jwt.py"])
store.declare_state("task", "fix the refresh race", "s1", "agent")
store.knowledge.topics()                             # browse: listings only, no bodies
store.artifacts.find_part("refresh")                 # where is it defined?
store.state.overview()                               # level 0: what matters now, in about 200 tokens
```

```bash
cd packages/agent-memory
uv sync --locked --extra dev
uv run pytest -q
uv run amem --project /path/to/project reconcile    # also: where, verify, checkpoint, recover, rebuild
```

## Not built yet

- **The context manager (Stage 2.10):** budgets, loading, offloading, restoring, and recovery after compaction, plus the tools agents call.
- **Stage 2.11:** purge, storage reporting and tiered compression.
- **Phase 3:** the agent plugins and onboarding.

Known problems are tracked as [follow-up issues](https://github.com/AdamMostofi/ADAM/issues?q=is%3Aissue+is%3Aopen+label%3Afollow-up).
