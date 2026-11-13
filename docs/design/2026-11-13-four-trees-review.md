# Four Trees Review: Did the Engine Drift From the Original Design?

**Status:** Proposed (2026-11-13), for the owner to decide as D10. No code changes until it is decided.
**Compares:**
- the owner's original memory design (two pasted messages, 2026-11-06 and 2026-11-09);
- [engine design revision 2](2026-11-06-agent-memory-engine.md);
- the code built in Stages 2.1 to 2.5 (`packages/agent-memory/`).

## Short answer

**Partly, yes.** All four parts of the original design are present in revision 2, and the built code is the right foundation for them. Two things were narrowed, though, and one was never designed:

1. **The four trees were merged into one graph.** They have no separate entry points.
2. **The knowledge tree is thin.** The file tree is code-only.
3. **Offloading context was never designed.** Revision 2 covers loading context on demand, but not managing what stays loaded.

None of this needs a rewrite. The fix is mostly a navigation layer, plus some new record types and context management. Most of it can live in Stage 2.6.

## What the original design asked for

**From the first message ("Don't make one tree"):** four parts over one object store, each with its own retrieval strategy, "because different questions require different retrieval strategies".

| # | Tree | Holds | Example question |
|---|---|---|---|
| 1 | Historical tree | Conversations, branches, decisions and how they evolved | "What did we decide three days ago?" |
| 2 | File graph | Files, symbols, dependencies, versions | "Where is the authentication function?" "What depends on it?" |
| 3 | Knowledge index | Decisions, requirements, explanations, bugs and solutions | "Why did we implement JWT?" |
| 4 | Active state | Goals, progress, constraints, next steps | "What is the current status?" |
| + | Object storage | Immutable content, by hash | "What did this file look like before?" |

All four sit on top of **progressive retrieval**, so the model gets only the context it needs, "while allowing it to retrieve everything else".

**From the second message:**
- the permanent core is the historical tree, file history, knowledge graph and raw archive;
- a dynamic active context;
- levels 0 to 4.

**From the owner, 2026-11-13:** a tree for each thing, four in total, each made for an agent to navigate easily. Context is offloaded and onloaded dynamically, so no context limit is reached and everything is "at its fingertips". The core use is coding, but the engine is not limited to coding.

## Comparison

| Original | Revision 2 (design) | Built (Stages 2.2 to 2.5) | Verdict |
|---|---|---|---|
| Historical tree | 6.1 tree, 6.2 development paths | `structure.py` nodes and edges; `navigate.project/session/event/tree/trace` | **Present.** Stored in a graph shared with knowledge and planning |
| File graph | 7.1 file history, 7.2 code dependency graph | `file_versions`, `codegraph.py` (Python and TypeScript imports), `navigate.file` | **Partial.** No **symbol index** ("where is the function?"); imports only. Code only: documents and other files get versions but no structure |
| Knowledge index | 6.3 relationship graph, 6.4 planning records | decision, path, goal, task, blocker and note records; typed edges with a basis | **Thin.** Decisions and paths exist. **Requirements, explanations, and bugs with their solutions** have no record types, and nothing organizes knowledge by topic, so it is a graph of records rather than a tree to browse |
| Active state | 9 active context, 10 sections | not built (Stage 2.6) | **Designed, not built** |
| Object storage | 5.2 raw archive | `archive.py` (compressed, encrypted, content-addressed) | **Present** |
| Progressive retrieval (onload) | 9.2 levels 0 to 4 | not built (Stage 2.6) | **Designed, not built** |
| Offload / no context limit | not designed | none | **Missing.** Revision 2 delivers context at session start and on request. Nothing tracks what the agent has loaded, gives it back as pointers, or restores the working set after the agent compacts its context |
| Separate trees for separate questions | Tools are organized by operation (`mem_tree`, `mem_node`, `mem_trace`, `mem_search`), not by tree | one generic navigation | **Narrowed.** An agent must know node ids and edge types. There is no "open the knowledge tree" |
| Not limited to coding | "for coding agents" throughout | event schema is domain-neutral; code graph and git reconciliation are code-specific | **Narrowed in wording and in the file tree.** The core itself is neutral |

## Why it happened

Revision 2 was written as an audit against the nine requirements in the second message. That message refined the first design: it was not a replacement. But the four-tree framing and the offload goal came only from the first message, so they weren't carried into the nine requirements, and nothing checked them.

Storing every record in one node and edge table was an engineering choice: one rebuild, one integrity check, one place for cross-links. It was right for storage. The mistake was letting it also become the **navigation** model.

## What is still correct

- **Keep one storage graph.** Cross-tree links are the point of the design: a decision links to the files it shaped, and a bug links to the session that fixed it. Four separate databases would lose them. The trees should be **views with their own roots and indexes** over the shared core, which is how the original design described them ("indexes" over shared object storage).
- **Keep everything built so far.** The log, archive, structure, code graph, verification, reconciliation and recovery are all needed by the four trees.

## Proposed correction (D10)

**1. Four named trees, each with its own root.** Each tree is navigated by path, and its first level is a short listing: names and counts, never contents.

| Tree | Root lists | Drill-down |
|---|---|---|
| `history` | sessions by date, development paths | session → turns → events → raw content |
| `files` | directories | file → versions, symbols, dependencies, verifications |
| `knowledge` | topics | topic → decisions, requirements, explanations, bugs with solutions, each linked to its evidence |
| `state` | the ten active-context sections | section → items → evidence |

Tools become `mem_open(tree, path, depth)` and `mem_find(tree, query)`, plus the existing `mem_get` and `mem_trace` for cross-tree links. They replace the operation-based list in section 10.

**2. A real knowledge tree.**
- New record kinds: `requirement`, `explanation`, `bug`, `solution`. A solution fixes a bug, and a bug is found by a verification.
- A `topic` hierarchy, declared by the agent or the user, and inferred only with an `inferred` basis label.

**3. Files, not just code.**
- A symbol index from tree-sitter, which is already a dependency: definitions, with file and line.
- A pluggable structure parser per file type: code (imports, symbols) and documents (Markdown headings, sections, links), with more later.

This keeps coding as the core use case while making the file tree useful for writing, research, and ADAM's books (Phase 4).

**4. Context working set: offload and onload.**
- The engine keeps a per-session ledger of what it has handed the agent (tree path, level, approximate tokens) and a budget, which is a setting.
- `mem_open` returns content plus a handle.
- When the budget is near, or the agent calls `mem_unload(handle)`, the engine gives back a one-line pointer to replace it.
- **On compaction** (the PreCompact hook, where an agent has one), the engine re-injects level 0 and level 1 plus an index of the pointers that were loaded. After compaction, everything the agent had is one recall away.

This is the "no context limit is reached" guarantee. The engine can't free the agent's context window itself; it makes dropping and reloading cheap and exact.

**5. Wording.** State in section 1 that the engine is domain-neutral, with coding as the primary use.

## Where it would go

Stage 2.6 ("Open the Archive") already owns the active context, retrieval levels, MCP tools and the CLI, so points 1, 4 and 5 fit there. Points 2 and 3 are new structure.

| Option | Stages |
|---|---|
| **A (recommended)** | Add **Stage 2.6 "Plant the Four Trees"** (points 1 to 3 and 5). Then **2.7 "Open the Archive"** (active context, levels, the context working set, MCP and CLI). Then **2.8 "Burn the Leak"** (purge, storage reporting, tiered compression for D3, CI) |
| **B** | Put everything in the current Stage 2.6. Fewer stages, but one stage becomes very large |

Stage 2.5 ("Survive the Crash") is unaffected and continues as planned.

## Questions for the owner
1. **Trees as views:** are the four trees as **views over one shared graph** (cross-links kept) what you meant, or did you mean four physically separate stores?
2. **Knowledge kinds:** is the knowledge tree's content right (decisions, requirements, explanations, bugs and solutions, by topic)? Is anything missing, such as skills or procedures for ADAM?
3. **Stages:** option A (new stages, renumbering 2.6 and 2.7) or option B?
