# Lossless Tree Memory: Architecture Revision 3

**Status:** Current. Accepted by the owner on 2026-11-13 (D10 to D13). It reconciles the built engine with the original four-tree design, and supersedes sections 3, 6, 9, 10 and 15 of [revision 2](2026-11-06-agent-memory-engine.md), and the [four-trees review](2026-11-13-four-trees-review.md). Stage issues: #85 (2.6), #86 (2.7), #87 (2.8), #55 (2.9), #88 (2.10), #76 (2.11).

**The principle this revision protects:** the entire history is kept permanently, but the agent loads only what it needs, from the right tree, at the right time. Everything stays reachable without overwhelming the active context window.

**What this is:** a general-purpose, lossless, hierarchical memory and context-management system for long-running AI agents. Software development is the primary use, not the boundary.

---

## 1. Sources reconciled

| # | Source | Key requirements |
|---|---|---|
| S1 | Owner's first design (2026-11-06) | Don't make one tree. Separate structures because "different questions require different retrieval strategies". Progressive retrieval. Five principles: lossless history, immutable objects, multiple indexes, authoritative state, progressive retrieval. Agent-independent engine |
| S2 | Owner's critique of revision 1 (2026-11-09) | Nine requirements: first-class tree, development-history branching, relationship graph, structured active context, full raw preservation, recovery, causality, stronger verification, canonical events |
| S3 | Owner, 2026-11-13 | "A tree for each thing", four in total, built for an agent to navigate. Dynamic offloading and onloading, so no context limit is reached. Not limited to coding |
| S4 | Owner's review, 2026-11-13 | Four specialized memory systems on one shared store. A cross-tree relationship layer. A dynamic context manager as a first-class subsystem. Domain neutrality ("Artifact Tree"). Security-filtered versus lossless content stated honestly. Attribution confidence in every tree. Agent-agnostic from the start |

---

## 2. Audit: requirements against what is built

Status values:
- **Built:** implemented and tested.
- **Partial:** some of it is built.
- **Missing:** not built.
- **Limit:** can't be fully satisfied; see section 11.

Code references are to `packages/agent-memory/src/agent_memory/`.

| Requirement | Source | Status | Where, and what's missing |
|---|---|---|---|
| Lossless history of everything permitted | S1, S2 | **Built** | `store.append`, append-only `events` with triggers, `archive.py` (whole content, compressed, encrypted, content-addressed) |
| Immutable, content-addressed objects | S1 | **Built** | `archive.Archive.put`: keyed HMAC ids, deduplicated |
| Secrets redacted, with a record | S2, S4 | **Built** | `secrets.SecretScanner.redact` returns `Redaction` records stored on the event (`Event.redactions`) |
| Explicit exclusion records | S2, S4 | **Built** | `exclusion` events (`store._excluded`) |
| Honest gap records | S2, S4 | **Built** | `capture_gap` events; `safe_append` and a content-free spool |
| Canonical, agent-independent event format with completeness | S2, S4 | **Built** | `schema.py` (`EventInput`, `COMPLETENESS`) |
| Hash chains, integrity verification | S2 | **Built** | per-writer chains; `store.verify()` |
| Checkpoints, crash recovery, replay | S2 | **Built** | `recovery.py`; 40 of 40 random-kill trials match a clean replay |
| Reconciliation with files and git | S1, S2 | **Built** | `reconcile.py`; 20 seeded scenarios, none misattributed |
| Concurrent writers, conflicts | S2 | **Built** | conflict records (`reconcile.py`, `structure._planning`) |
| Stronger verification records | S2 | **Built** | `verification.py`; `store.record_verification`; stale reasons |
| Causal relationships | S2 | **Built** | 28 edge types (`structure.EDGE_TYPES`), including caused_by, based_on, reverts, verified_by |
| Relationship basis: observed, declared, inferred | S2, S4 | **Partial** | edges carry `recorded`, `declared` or `inferred` (`structure.BASES`). File-change attribution is a label without a basis (fixed in 2.6) |
| Development-history branching | S2 | **Built** | development paths with statuses (`structure._planning`, `_propose_path`) |
| **Four independent trees** with their own roots, schemas, indexes and navigation | S1, S3, S4 | **Partial** | the records exist, but everything lives in one generic `nodes`/`edges` graph. Navigation is generic (`navigate.tree/trace/node`) and needs ids and edge types. There are no tree roots or per-tree schemas, indexes or interfaces |
| Historical tree | S1, S2, S4 | **Built** (as part of the one graph) | project, session, turn and event nodes; `navigate.project/session/event` |
| Artifact tree: files, versions, dependencies | S1, S4 | **Partial** | `file_versions`, `codegraph.py` (Python and TypeScript imports) |
| Artifact tree: symbols | S1, S4 | **Missing** | no symbol index |
| Artifact tree: documents, media, datasets, designs | S4 | **Missing** | versions are kept, but there's no structure (headings, sections, metadata) |
| Knowledge tree: decisions, rejected approaches with reasons | S1, S4 | **Built** | decision and path records with statuses and reasons |
| Knowledge tree: requirements, concepts, explanations, discoveries, bugs, solutions | S1, S4 | **Missing** | no record kinds; notes only |
| Knowledge tree: topic hierarchy | S3, S4 | **Missing** | only a `topic` string on paths |
| Active State tree | S1, S2, S4 | **Missing** | goal, task and blocker records exist. Nothing builds the state tree, its sections or levels (was Stage 2.6) |
| Cross-tree relationship layer | S4 | **Partial** | cross links exist as ordinary edges, but nothing separates a tree's own structure from links between trees |
| Progressive retrieval (levels 0 to 4) | S1, S2 | **Missing** | designed in revision 2, section 9.2 |
| Dynamic context manager: ledger, budgets, offload, restore, compaction recovery, protection | S3, S4 | **Missing** | never designed before this revision |
| Domain neutrality | S3, S4 | **Partial** | the event core is neutral. The artifact layer is code-only, and the reconciler is git-first with a walk fallback for folders without git |
| Agent-agnostic from the start | S1, S4 | **Built** for the core | the engine imports no agent code, and adapters translate into canonical events. The context manager must also live in the engine (section 7) |
| Tiered lossless compression | D3 | **Missing** | planned |

**Summary:**
- The **storage, integrity, recovery and history foundation is built and reusable**.
- The **organization** (four trees) and **context management** are the missing architecture.
- Domain neutrality is **partly** a naming problem and partly a missing artifact layer.

---

## 3. What is reused, extended, or changed

| Component | Verdict | Change |
|---|---|---|
| `schema.py`: canonical events | **Reuse** | Add event kinds for knowledge entries, artifact declarations and context lifecycle (5.3, 7.4) |
| `archive.py`, `keys.py`, `secrets.py` | **Reuse** | Unchanged. Tiered compression arrives later (Stage 2.11) |
| `store.py` write path, chains, `verify`, spool | **Reuse** | `verify` grows per-tree checks |
| `recovery.py` | **Reuse** | Checkpoints also snapshot the context ledgers |
| `reconcile.py` | **Extend** | Add a basis to every attribution (observed, inferred, unattributed) |
| `verification.py` | **Reuse** | Becomes a software-profile extension (section 8) |
| `structure.py`: one node and edge table | **Change** | Each node belongs to exactly one tree, through a `tree` column. Per-tree schemas say which node types, statuses and children are allowed. Edges inside a tree build that tree; edges between trees form the cross-tree layer (4.5). One shared table stays: it is storage, not navigation |
| `navigate.py`: generic navigation | **Change** | Replaced at the interface by four tree navigators (4.1–4.4). The generic functions stay internal |
| `codegraph.py` | **Extend** | Becomes the code parser of the artifact layer, adding symbols. A document parser is added beside it (Markdown and text headings and sections) |
| `location.py` (D3) | **Reuse** | |
| New: `trees/` (`history.py`, `artifacts.py`, `knowledge.py`, `state.py`) | **New** | Per-tree schema, indexes and navigation |
| New: `context/` (ledger, budget, relevance, assembler) | **New** | The context manager (section 7) |
| New: `profiles/` (software, documents, generic) | **New** | Domain extensions (section 8) |

**Migration is non-destructive.** The log is never changed, and the new structure is rebuilt from the existing log by replay, which is already tested. The store format number goes up, and old stores are rebuilt when they are opened.

---

## 4. The architecture

```text
 Agent clients: Claude Code, OpenCode, Pi, Codex, ADAM ...   (adapters: translate + deliver)
        |  canonical events in              context packets out  ^
        v                                                       |
 +--------------------------------- MEMORY ENGINE ------------------------------------+
 |  Ingestion: normalize, provenance, completeness, redaction, exclusion, gaps         |
 |                                                                                      |
 |  HISTORICAL TREE      ARTIFACT TREE       KNOWLEDGE TREE       ACTIVE STATE TREE     |
 |  what happened        what exists         what we know         what matters now      |
 |       \__________________ CROSS-TREE RELATIONSHIP LAYER __________________/         |
 |                                                                                      |
 |  DYNAMIC CONTEXT MANAGER: ledger, budgets, relevance, load/offload/restore,          |
 |                           compaction recovery, protection                            |
 |                                                                                      |
 |  MEMORY CORE: event log (truth), immutable object store, indexes, integrity,         |
 |               checkpoints, recovery, reconciliation, profiles                        |
 +--------------------------------------------------------------------------------------+
```

**Rules:**
- **Trees are built from the log.** Each tree is a deterministic function of the event log, as now. The log is the only truth, and every tree can be rebuilt.
- **One tree per node.** Every node belongs to exactly one tree. A thing that matters to several trees is several nodes, joined by cross-tree links. For example, a decision is a knowledge node; the discussion that produced it is a history node; and its effect "now" is a state item. One record never belongs to several trees at once.
- **Each tree has its own:**
  - root (`history:`, `artifacts:`, `knowledge:`, `state:`);
  - schema (node types, statuses, allowed children);
  - indexes;
  - navigator and retrieval tool;
  - context budget share.
- **Every node and every link carries a basis:**
  - `observed`: the engine saw it happen through an instrumented operation (today's `recorded`);
  - `declared`: an agent or the user stated it;
  - `inferred`: the engine derived it from evidence, with the rule named;
  - `unattributed`: for actors only, where the evidence is insufficient.

  `inferred` items never enter injected context as facts.

### 4.1 Historical Tree: what happened

| | |
|---|---|
| **Root** | `history:` → projects → sessions (by date) → turns → events |
| **Node types** | `session`, `turn`, `event` (one per log event), `branch` (session forks and resumes, Pi-style session trees) |
| **Statuses** | session: `open`, `ended`, `crashed` (inferred: started, never ended) |
| **Indexes** | time (session start and end, event position); kind; agent and writer; FTS5 over message and tool-output text (permitted content only) |
| **Navigator** | `history.list(range)`, `history.open(path, depth)`, `history.around(event, n)`, `history.search(q, filters)` |
| **Built today** | session, turn and event nodes, `contains` and `follows` edges, session links (resume, fork) |

### 4.2 Artifact Tree: what exists or has existed

| | |
|---|---|
| **Root** | `artifacts:` → collections (folders, or a profile's grouping) → artifacts → versions; artifacts → parts (symbols, sections, scenes ...) |
| **Node types** | `collection`, `artifact` (any file or resource: code, document, image, video, dataset, design), `version` (content id, size, change, attribution and basis), `part` (a structural piece from a parser: `symbol` in code, `section` in documents, profile-defined elsewhere) |
| **Statuses** | artifact: `present`, `deleted`, `renamed` |
| **Indexes** | path; content id (find all versions with this content); part name (the **symbol index**: "where is the authentication function?"); dependency edges (imports, links between documents, includes); media type; FTS5 over text artifacts |
| **Navigator** | `artifacts.open(path)`, `artifacts.versions(path)`, `artifacts.find_part(name, kind)`, `artifacts.depends(path, direction, depth)`, `artifacts.at(path, version)` |
| **Parsers** | from profiles. Software: tree-sitter Python and TypeScript (imports today, symbols next). Documents: Markdown and plain-text headings and sections, and links. Generic: metadata only (type, size, versions), so a video or spreadsheet is still versioned and linkable without a parser |
| **Built today** | file nodes, `file_versions`, rename and revert detection, the code import graph, verification relevance |

### 4.3 Knowledge Tree: what is known

| | |
|---|---|
| **Root** | `knowledge:` → topics (a hierarchy) → entries |
| **Entry kinds (core)** | `decision`, `requirement`, `constraint`, `concept`, `explanation`, `discovery`, `bug`, `solution`, `approach` (development paths: selected, abandoned and reconsidered, with reasons), `question`, `reference` (an external source) |
| **Entry kinds (profiles)** | for example `character` and `narrative_rule` (creative), `market_fact` (business), `procedure` and `skill` (ADAM) |
| **Statuses** | per kind. decision: `proposed`, `active`, `superseded`. requirement: `open`, `met`, `dropped`. bug: `open`, `fixed`, `wontfix`. approach: as paths today |
| **Topics** | declared by the agent or the user (`mem_topic`). A rule can propose a topic from structure (for example, the artifact path an entry concerns) with basis `inferred`. Entries can sit under several topics through `filed_under` links; one home topic is required |
| **Indexes** | kind, status, topic, FTS5 over titles and bodies; supersession chains |
| **Navigator** | `knowledge.topics(depth)`, `knowledge.open(topic_or_entry)`, `knowledge.find(q, kind, status)`, `knowledge.history_of(entry)` (supersessions and evidence) |
| **Built today** | decision and path records (now `approach`), notes, typed edges |

### 4.4 Active State Tree: what matters now

| | |
|---|---|
| **Root** | `state:` → sections → items |
| **Sections** | `objectives`, `progress`, `tasks`, `blockers`, `priorities`, `constraints` (standing user instructions and rules), `open_conflicts`, `working_context` (what the current task is about: focus artifacts, topics), `verification` (verified, stale or unknown by area), `next_actions` |
| **Items** | declared (goals, tasks, blockers, priorities, constraints, next actions, progress notes) or generated from other trees (open conflicts, stale verifications, active decisions that apply, files changed since the last session) |
| **Statuses** | as today for goal, task and blocker. Each item shows its age and staleness (declared items go stale when the artifacts they name change, or by age) |
| **Indexes** | section, status, priority, focus (which artifacts and topics each item concerns) |
| **Navigator** | `state.overview()` (level 0), `state.section(name, level)`, `state.item(id)` |
| **Built today** | goal, task and blocker records with statuses; verification status. Sections and generation are missing |

### 4.0 As built (Stage 2.6, #85)
- **Trees** (`structure.py`):
  - every node has a `tree` and a `basis` column;
  - the roots are `history:`, `artifacts:`, `knowledge:` and `state:`;
  - `SCHEMAS` lists each tree's node types and what each may contain, and is checked on every write;
  - `contains` edges can't be declared or retracted.
- **Knowledge groups** (`approaches`, `decisions`, `notes`) and **state sections** (`objectives`, `tasks`, `blockers`, `open_conflicts`) are created on first use. Topics arrive in 2.8, and more sections in 2.9.
- **Stable ids:**
  - planning records keep `<kind>:<event id>`;
  - a development path is a knowledge `approach` with id `path:...`;
  - artifacts are `artifact:<path>`, under `collection:<folder>` nodes;
  - a legacy `file:<path>` in the log resolves to the artifact (`structure.resolve`).
- **Navigators** (`trees.py`): `store.history`, `store.artifacts`, `store.knowledge`, `store.state`, each with `root()`, `open()`, `links()` and `schema()`, plus per-tree lookups (`sessions`, `open_path`, `versions`, `find`, `section`). Listings are short entries (id, type, label, status, basis, child count, link counts by tree). A navigator returns nothing for another tree's node.
- **Cross-tree layer:**
  - edges carry `cross_tree`, which is indexed;
  - `store.links(node, to_tree, types)` follows only cross links;
  - `verify` checks every tree's shape (exactly one container per node) and every cross flag.
- **Basis:**
  - `observed` replaces `recorded`;
  - structural path proposals are `inferred`, with the rule named;
  - file versions record `attribution` and `attribution_basis`: `agent_tool` and `baseline` are observed; `git_operation`, `agent_bash` and `external` are inferred; `unattributed` has none; changes an adapter reported are `declared`.
- **Profiles** (`profiles.py`):
  - `generic` (always on) and `software` (the default pair);
  - they are stored in the store;
  - without `software`, verification is refused (`ProfileError`), the code graph is skipped, and reconciliation walks the folder even in a git repository.
- **Store format 2:**
  - an older store rebuilds its structure from the log when opened, in one transaction, and records a `recovery` event (`op: migrate`);
  - older checkpoints are reported as superseded, not corrupt, and a fresh checkpoint is taken;
  - tested with a store written by the real Stage 2.5 code.

### 4.5 Cross-tree relationship layer

- **What it is:** a link whose ends are in different trees. It is stored in the shared edge table and marked `cross`, with its own index: from-tree, to-tree, type, basis.
- **Types:** the existing 28 edge types, plus `filed_under`, `concerns` (a state item to the artifacts or topics it is about), `evidence_for` and `discussed_in`.
- **Navigation:** `mem_links(node, to_tree, types)` follows only cross links. A tree navigator never wanders into another tree by itself. It shows that links exist ("3 history links, 2 artifact links"), and the agent chooses to follow one.
- **Example:** a decision (knowledge) is `discussed_in` turn 14 of session 9 (history). It `concerns` `src/auth/jwt.py` (artifacts), and it `blocks` task "add refresh rotation" (state). Each link's basis is shown.

---

## 5. Shared core details

### 5.1 Preservation classes (stated honestly)
Every piece of captured content is in exactly one class, and the class is recorded:

| Class | Meaning | Record |
|---|---|---|
| `preserved` | Kept byte for byte | object id |
| `redacted` | Kept, with secrets replaced by `[SECRET:rule:fingerprint]` markers | redaction records on the event: rule, field, position, fingerprint. The secret itself is never stored |
| `excluded` | Not kept, by an explicit exclusion rule | `exclusion` event with the path, rule and size |
| `gap` | Should have been kept but wasn't (engine failure, agent API limits) | `capture_gap` event with the reason; completeness `partial` or `unavailable` |

"Lossless" in this project means **lossless for permitted content**. Redacted, excluded and gap content is never presented as complete. That is how it works today; revision 3 only names it.

### 5.2 Store format
- One SQLite database plus the object store, in `<project>/.agent-memory/` (D3).
- `nodes` gains `tree`, and edges gain `cross`, both derived.
- Per-tree index tables: `history_fts`, `artifact_parts`, `artifact_fts`, `knowledge_topics`, `knowledge_fts`, `state_items`.
- Context ledger tables (section 7).

### 5.3 New event kinds
- Knowledge: `entry` (create or status change for any knowledge kind), `topic`.
- Artifacts: `artifact_note` (a declared fact about an artifact, for example "deprecated").
- State: `state_item` (priority, constraint, next action, progress).
- Context: `context_load`, `context_offload`, `context_restore`, `context_pin`, `context_reset` (7.4).

Existing kinds (goal, task, blocker, decision, path, note) remain and map onto the trees, so no existing log needs rewriting.

---

## 6. Retrieval interface (replaces revision 2, section 10)

**Per-tree tools.** Each loads only on demand where the agent supports it:

| Tool | Tree |
|---|---|
| `mem_history(op, ...)` | Historical |
| `mem_artifacts(op, ...)` | Artifact |
| `mem_knowledge(op, ...)` | Knowledge |
| `mem_state(op, ...)` | Active State |

**Cross-cutting tools:**
- `mem_links(node, to_tree, types)`: cross-tree links.
- `mem_get(handle_or_id, page)`: raw content, paged.
- `mem_load(ref, level)`, `mem_offload(handle, keep)`, `mem_restore(handle)`, `mem_pin(handle)`: context control (section 7).
- `mem_declare(kind, ...)`: one declaration tool covering goals, tasks, blockers, decisions, entries, topics, priorities and constraints, to keep the tool count low.

**Response format:**
- Every result is a **context packet**: a handle, the tree and path, level, approximate tokens, basis and age, and links summarized as counts.
- Content is bounded by the level; deeper levels are paged.
- Retrieved content is labelled as data, never as instructions.

**CLI:** `amem history|artifacts|knowledge|state|links|get|context|declare ...`, mirroring the tools.

---

## 7. Dynamic context manager

### 7.1 What it is, and what it is not
It is **not** a summarizer and **not** just retrieval tools. It is the subsystem that decides, for each model request it can influence, **which memory goes into the model's context, at what level of detail, and what is replaced by a reference**. It keeps a durable record of those choices so that it can restore them.

It runs inside the engine. Adapters only deliver its output, so every agent gets the same behaviour (agent-agnostic, S4).

### 7.2 Ledger (what is in the working context)
One ledger per agent session:

| Field | Meaning |
|---|---|
| handle | `c12`, stable for the session |
| ref | tree, node id and level |
| origin | which tree and record it came from, and why it was loaded (prompt mention, task focus, agent request, restoration) |
| state | `loaded`, `offloaded` (reference only), `pinned` (never offloaded automatically) |
| tokens | an estimate (4 characters per token by default; an adapter can supply the model's tokenizer) |
| priority | P0 to P3 (7.3) |
| last_used | the last time the agent referred to the handle, or a tool touched the node |
| keep | findings the agent kept when offloading (a declared note) |

**The ledger is rebuilt from `context_*` events**, so it survives crashes, appears in history ("what did the agent know when it made decision X?"), and is included in checkpoints.

### 7.3 Budgets, priorities, relevance
- **Total budget:** a setting per model. For example, 6k tokens for a 4B local model, 40k for a large model.
- **Tree shares:** defaults are state 30%, knowledge 25%, artifacts 25%, history 20%. These are settings, and unused share flows to other trees.
- **Priorities:**

| Priority | What | Offloaded automatically? |
|---|---|---|
| P0 | Constraints and standing user instructions; the active objective; open conflicts; unresolved blockers and in-progress tasks of the current focus; active decisions that apply to the focus | **Never.** Only the user or an explicit `mem_offload` can, and that is recorded |
| P1 | The current task's working set | Last |
| P2 | Supporting context (related decisions, dependencies) | When over budget |
| P3 | Background (history references) | First |

- **Relevance scoring:** deterministic, with no model in the core. It is a weighted sum of:
  - an explicit mention in the prompt (paths, symbol names, ids, topic names);
  - distance through links from the current focus;
  - status (open before closed);
  - recency of change;
  - an FTS5 match score.

  The weights are settings. The reasons are shown with each packet ("loaded because: mentioned `jwt.py`; links to open task t7").
- **Eviction when over budget:** P3 first, then P2, least recently used and largest first. Each evicted item becomes a **reference line**:
  `[c12] bug: JWT refresh race (knowledge/auth) - fixed, session 41 - offloaded; mem_restore c12`
  A reference line is about 20 tokens, so the whole working set stays visible as an index even when its content isn't.

### 7.4 Lifecycle operations
| Operation | Trigger | Effect |
|---|---|---|
| **Assemble** | Session start, new session, after compaction | Level 0 overview (about 200 tokens) + P0 items in full + level 1 state + reference lines for the last session's working set |
| **Onload** | Prompt mentions, the agent calls `mem_load` or a tree tool, task focus changes | Adds packets within budget. Reports what didn't fit, as reference lines |
| **Offload** | Over budget, task completed (its task moves to done), or `mem_offload(handle, keep=...)` | Content is replaced by its reference line. `keep` is stored as a declared note linked to the record, so findings survive |
| **Restore** | `mem_restore(handle)`, or a prompt mentions an offloaded item | The packet comes back at its earlier level |
| **Protect** | Before any offload or compaction | Checks that all P0 items are present, and that unresolved tasks, conflicts and constraints are listed. Refuses an automatic offload of P0 |
| **Detect missing context** | Each prompt | Finds names in the prompt that memory has records for but the working set doesn't contain, and offers them as reference lines ("memory has 4 records on `refresh token`: c31-c34") |
| **Compaction recovery** | The agent's compaction (where an adapter can see it) | Before: write a `context_reset` event holding the ledger. After: run Assemble from that ledger |

### 7.5 How it reaches the model: three integration tiers
The engine can't delete tokens from a context window that the agent controls. What it can control depends on the client, so each adapter declares its tier:

| Tier | Clients | How subsequent model requests are managed |
|---|---|---|
| **A: request control** | ADAM (Phase 4), agents built on an SDK loop, a local proxy in front of a model API | The engine assembles **every request**: static instructions, then P0, then the working set, with offloaded items as reference lines only. True offload: offloaded content is no longer sent. |
| **B: hooks** | Claude Code, OpenCode and Pi, where each supports it (to be verified per agent in Phase 3) | **Session start:** inject the Assemble output. **Each prompt:** inject only the delta (new packets, newly relevant reference lines, missing-context offers) through the prompt hook's added context. **Compaction:** where the client signals it (for example a session-start event with a compact source), inject a full Assemble right after. **Offload** marks the ledger and takes effect at the next compaction or new session, because content already in the window stays until then. **Tool results** are bounded packets, never whole histories. |
| **C: tools only** | Agents without hooks, or MCP only | The agent pulls with the tools, and the ledger records deliveries. Restoration happens when the agent calls `mem_state('overview')` at the start, as its plugin instructions tell it to |

So a **true** guarantee that memory never overfills the context is possible only in tier A. Tier B guarantees that **the engine's own contribution** stays within budget, and that everything is restorable after compaction. See section 11.

---

## 8. Domain neutrality: core and profiles

- **The universal core:** the four trees, their generic node types, the cross-tree layer, the context manager, and the preservation classes.
- **Profiles add domain behaviour on top**, and a project can enable several:

| Profile | Adds |
|---|---|
| `generic` (always on) | Artifact metadata and versions for any file; the core knowledge kinds; the core state sections |
| `software` | Code parsers (imports, symbols), git reconciliation and attribution, verification records, the `bug`/`solution` emphasis, the test-environment fingerprint |
| `documents` | Markdown and text structure (sections, links), document versions |
| `creative` (later) | Knowledge kinds `character`, `narrative_rule`, `scene_note`; artifact parts for scripts (scenes) |
| `research`, `business` (later) | `reference`, `claim`, `market_fact`; state sections such as `opportunities` |
| `adam` (Phase 4) | Knowledge kinds `procedure`, `skill`, `proof_record`; book artifacts |

- **Reconciliation:** git is a profile accelerator. The core reconciler walks any folder; the software profile adds git status and reflog attribution, as built.
- **Choosing profiles:** they are offered at onboarding, alongside the key-storage choice (D4).

---

## 9. End-to-end example: a long project

A software project, with a mid-size model and a 12k-token memory budget, in a tier B agent (Claude Code style).

**Session 1, the start.** Memory is empty. The user says: "Build user auth with JWT. Never store tokens in localStorage."

- The adapter records the `user_message`.
- The agent declares:
  - objective `o1` "user auth with JWT" (state);
  - constraint `k1` "never store tokens in localStorage" (state, **P0**, `discussed_in` turn 1);
  - decision `d1` "JWT with refresh rotation" (knowledge, topic `auth`, status `proposed`, `discussed_in` turn 1).
- The agent edits files. The reconciler records versions of `src/auth/jwt.py` and `src/auth/routes.py` (artifacts, attribution `agent_tool`, basis `observed`). The code parser adds parts `issue_token`, `refresh` and an import edge.
- A test run is recorded, with relevance computed from the import closure.

**Session 9, a bug.** The prompt says: "Refresh fails randomly in prod."

1. **Assemble** (about 1.4k tokens):
   - the level 0 overview;
   - P0: constraint `k1`, objective `o1`, the in-progress task;
   - the level 1 state;
   - reference lines from session 8's working set.
2. **Detect missing context:** "refresh" matches the symbol `refresh` (artifacts), decision `d1` (knowledge) and two history turns. The engine adds them as reference lines `c4`–`c7`.
3. The agent calls `mem_knowledge(open, "auth")` and gets packet `c8`: topic `auth` with 6 entries at level 1 (380 tokens).
4. The agent calls `mem_artifacts(find_part, "refresh")` and gets `c9`: the part `src/auth/jwt.py:refresh`, its version history and 2 dependents (520 tokens).
5. The agent investigates and declares:
   - `bug b1` "refresh race when two tabs refresh at once" (knowledge, `concerns` `jwt.py`);
   - later, `solution s1` "single-flight lock on refresh" (`fixes` `b1`, `evidence_for` the passing test run).
6. Task `t3` moves to done. **Offload:** `c8` and `c9` become reference lines. The agent kept "race fixed by single-flight lock; see s1". About 900 tokens are released for the next model request in tier A, and at the next compaction in tier B.

**Session 9, later.** The agent's own context fills, and the client compacts.
- **Before:** a `context_reset` event records the ledger.
- **After:**
  1. Assemble re-injects the overview and P0 (constraint `k1` is still there: protected).
  2. The open conflict on `routes.py`, edited by two agents, is injected as P0.
  3. The working set comes back as reference lines `c1`–`c12`.
- Nothing the agent was relying on is lost, and anything can be restored with one call.

**Session 40, months later.** A new agent (OpenCode) opens the project and asks: "Why do we use a refresh lock?"
- `mem_knowledge(find, "refresh lock")` returns `s1`.
- `mem_links(s1, "history")` returns the turns in session 9 where it was found.
- `mem_links(s1, "artifacts")` returns the version of `jwt.py` that introduced it.

The same memory serves both agents, because the engine owns the trees and the ledger, and the adapters only deliver.

---

## 10. Revised plan (replaces revision 2, section 15)

Stages 2.1 to 2.5 are kept as built. The order follows the agreed priority: foundation, tree interfaces, artifacts, knowledge, state, context manager, integrations, validation.

| Stage | Name | Delivers | Was |
|---|---|---|---|
| 2.6 | **Plant the Four Trees** | Tree membership and roots, per-tree schemas and navigators, the cross-tree layer, a basis on every record (attribution included), rename file→artifact, the profile mechanism (`generic`, `software`), store format bump with rebuild-on-open | new |
| 2.7 | **Map the Artifacts** | Symbol index (Python, TypeScript), the `documents` profile (Markdown and text sections, links), metadata for any artifact, artifact FTS, tsconfig alias resolution (#78) | new |
| 2.8 | **Shape the Knowledge** | Knowledge entry kinds and statuses, the topic hierarchy, supersession chains, knowledge FTS, the history FTS index | new |
| 2.9 | **Hold the Present** | The Active State tree: sections, declared and generated items, staleness, levels 0 to 2, `state.overview` | from #55 |
| 2.10 | **Mind the Context** | The context manager: ledger events, budgets, priorities, relevance, Assemble, onload, offload, restore, protect, missing-context detection, compaction recovery; context packets; the per-tree MCP tools and CLI | from #55, new |
| 2.11 | **Burn the Leak** | Purge, storage reporting, tiered lossless compression (D3), verify from a checkpoint (#79), the full suite plus **context-limit stress tests** (a long synthetic project whose engine-delivered context never exceeds budget, while every record stays restorable) | #76 |
| 3.1 | First Plugin | The Claude Code adapter at tier B. Verify which hooks exist (prompt-time context, compaction signal), and capture the environment (#82) | #56 |
| 3.2 | Weigh the Thesis | The benchmark tests the complete design, including multi-session continuity after compaction, against compaction alone, and git plus notes | #57 |
| 3.3 to 3.6 | OpenCode, Pi, others, release | As planned, each adapter declaring its tier | #58 to #61 |
| 4.1 | Connect the Engine | ADAM at **tier A**: ADAM assembles every request through the context manager | #46 |

**Issues:** when this plan is accepted:
- #55 becomes 2.9;
- #76 becomes 2.11;
- four new stage issues are created (2.6, 2.7, 2.8, 2.10);
- the roadmap grows from 53 to 57 stages.

Nothing is renumbered before the owner accepts.

---

## 11. Requirements this architecture can't fully satisfy

These are stated plainly, not simplified away:

1. **Erasing tokens from a running context window.** Only the agent controls its window. The engine controls what it sends, and in tier A that is everything memory contributes. In tier B, offloaded content stays in the window until the client compacts or a new session starts.
2. **"No context limit is ever reached" for tier B and C agents.** The engine can't limit the agent's own file reads and tool output. It guarantees its own contribution stays within budget, and that everything is restorable after compaction. A full guarantee needs tier A.
3. **Knowing exactly what the model still holds.** The ledger knows what the engine delivered, not what the client's compaction kept. After a compaction, the engine assumes nothing survived and restores from the ledger.
4. **Semantic relevance without a model.** Core relevance uses mentions, links, status, recency and full-text search. It will miss purely semantic matches ("login problems" for a record titled "auth failure"). Embedding search is an optional extension after the benchmark (Stage 3.2), never the source of truth.
5. **Detecting missing context completely.** Detection finds named things that memory has but the working set lacks. It can't detect a need the prompt doesn't name.
6. **Literal losslessness.** Secrets are redacted and exclusions are honoured by design. These are recorded, never silent (5.1).
7. **Proving authorship of file changes.** File observation alone can't prove who changed a file. Attribution carries a basis, and `unattributed` is used whenever evidence is insufficient (#81).
8. **Deep structure for every domain.** Media, video and spreadsheets get versions, metadata and links from the generic profile. Parsing their insides (scenes in a video, sheets in a workbook) needs a profile parser, and none is planned beyond software and documents in Phase 2.
9. **Exact token counts.** Budgets use estimates unless the adapter supplies the model's tokenizer.

---

## 12. Decisions for the owner

| # | Question | Recommendation |
|---|---|---|
| D10 | Accept revision 3: four trees as independent structures over one shared store, a cross-tree layer, and the context manager | **Accepted 2026-11-13** |
| D11 | Plan: insert Stages 2.6 to 2.8 and 2.10; move #55 to 2.9 and #76 to 2.11 | **Accepted 2026-11-13** (57 stages) |
| D12 | Default context budgets and tree shares | **Accepted 2026-11-13:** as in 7.3, tuned with the benchmark |
| D13 | Profiles enabled in Phase 2 | **Accepted 2026-11-13:** `generic`, `software`, `documents`; others later, on demand |
