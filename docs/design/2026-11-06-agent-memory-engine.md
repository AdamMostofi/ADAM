# Lossless Tree Memory Engine: Design Spec and Test Plan

**Status:** Proposed, revision 2 (2026-11-09). Design only: **no engine code exists yet.** Work order: [ROADMAP.md](../ROADMAP.md), Phases 2 to 4.
**Working name:** `agent-memory`, command `amem`. The final name is decision D8.
**Relationship to ADAM:** A standalone product developed inside the ADAM repo until release. ADAM uses it through one interface ([#46](https://github.com/AdamMostofi/ADAM/issues/46)), and the engine never imports ADAM code.

Revision 2 restores the original goal, a **lossless, navigable, hierarchical memory of the whole development journey**, which revision 1 had narrowed into mainly an auditing and state-checking engine. Section 2 lists what changed and why.

All latency, size, and score numbers below are proposed targets, not results.

---

## 1. Purpose and principles

**The standard for success:** an agent can continue a complex engineering project with the same historical understanding and awareness of the present as if it had taken part in every earlier session.

### The three principles that override everything else
1. **Perfect historical recall.** Keep the whole development journey: conversations, attempts, mistakes, abandoned approaches, and the reasoning behind them.
2. **Accurate present-state reconstruction.** The agent knows what is true now, what changed, and what evidence supports that.
3. **Efficient contextual retrieval.** The agent loads exactly what it needs, at the level of detail it needs, without loading the whole history.

### The boundary rule
**The engine preserves evidence and makes it reachable. The agent interprets it.**
- The engine never decides what is true, what matters, or what should happen next.
- When the engine stores a relationship it did not observe directly, it labels where it came from (section 6.3).
- This is what lets different models and agents use the same memory without rebuilding it.

### Other fixed rules
- Capture happens at the agent boundary; the agent does not maintain its own memory files.
- The filesystem and git are the truth about code. The engine records observations of them and never edits project files.
- The permanent core is append-only. Indexes and the active context are derived from it and can be rebuilt.
- The core needs no model, network, or API key.

---

## 2. Requirement audit

**Implementation status of every requirement: not implemented.** No engine code exists. The table compares revision 1 of this document with the nine requirements, and says what revision 2 does.

| # | Requirement | Revision 1 | Revision 2 |
|---|---|---|---|
| 1 | First-class hierarchical tree | **Partial.** Events had parents and sessions could branch, but the tree was described as a way to view indexed events | The tree is a core structure with its own node and edge tables and navigation tools (6.1) |
| 2 | Development-history branching | **Missing.** Only session forks and replaced decisions existed | Development paths are first-class records, independent of git (6.2) |
| 3 | Relationship and dependency graph | **Partial.** A few fixed links; the code dependency graph was postponed until after the benchmark | Typed relationships among all records, plus an incrementally updated code dependency graph in the core build (6.3, 7.2) |
| 4 | Structured active context | **Partial.** Computed state plus a brief capped at 500 tokens | Ten independently retrievable sections over five levels; budgets are settings, not limits (9) |
| 5 | Complete raw preservation | **Conflict.** Outputs over 10 MB were partly kept; binary files kept as hash only | Everything is kept in full, compressed and content-addressed. Only secrets and paths you explicitly exclude are withheld, and each is recorded (5.3) |
| 6 | Recovery and reconstruction | **Partial.** Fail-open capture, crash-resolution for edits, reconciliation, tamper checks, index rebuild | Adds checkpoints, replay, an integrity command, and concurrent-agent conflict handling (8) |
| 7 | Causal relationships | **Partial.** Changes linked to the message that requested them, and to tool calls | Causal relationship types, each labelled by how it is known (6.3) |
| 8 | Stronger verification records | **Partial.** Command, exit code, output, and whole-tree hash | Adds commit, branch, relevant file hashes, environment and dependency fingerprints, and stale reasons (7.3) |
| 9 | Canonical event format | **Partial.** A normalized event list and gap records | A versioned canonical schema with capture completeness on every event and session (4) |

### Revision 1 decisions you reviewed

| Revision 1 decision | Revision 2 |
|---|---|
| No progress files maintained by hand | **Kept**, and agents or users can now set goals, tasks, blockers, progress notes, and decisions directly (9.3) |
| "Lossless" exceptions | **Changed:** only secrets and explicit exclusions are withheld |
| Separate indexes instead of one tree | **Changed:** separate indexes **and** a first-class tree |
| No AI summaries or similarity search at first | **Kept** for the core build |
| Benchmark can stop expansion | **Kept**; it now tests the complete core (12.2) |
| Agents without hooks get less | **Kept**, with completeness shown on every record |

### Existing ADAM code that might look relevant
None of it implements engine requirements. `memory/exact_store.py` stores facts, `memory/connection_graph.py` links fact terms, and `kernel/engine.py` keeps proof strings. Stage 4.1 connects ADAM to the engine; nothing is reused in the other direction.

---

## 3. Architecture

```text
 Agent adapters: Claude Code, OpenCode, Pi, Codex, others   (replaceable)
        |
        v
 Canonical ingestion: normalize, provenance, completeness, redaction
        |
        v
 PERMANENT CORE (authoritative, append-only)
   Event log ---- Historical tree ---- Development paths
        |               |                     |
   Raw archive    Relationship graph    File history
        |
        v
 DERIVED LAYER (rebuildable)
   Search, code dependency graph, verification status,
   integrity checks, previews, checkpoints
        |
        v
 ACTIVE CONTEXT (generated): sections and levels 0-4
        |
        v
 Retrieval interface: MCP tools, CLI, hook context injection
```

| Layer | Authority | If lost |
|---|---|---|
| Permanent core | The truth | Must not happen; protected by integrity checks and backups |
| Derived layer | Rebuildable | Rebuilt from the core |
| Active context | Computed on demand | Regenerated |
| Adapters | Translation only | Reinstalled; no data lives there |

### Technology
- SQLite (WAL mode) for records and FTS5 for search.
- Content-addressed, compressed, encrypted files for raw content.
- tree-sitter for code structure.
- Python for the prototype (decision D2).
- No background service: each hook runs as a short process, and the MCP server runs only during a session.

---

## 4. Canonical event format

Every adapter translates its agent's events into one versioned format. Memory looks the same whichever agent produced it.

| Field | Meaning |
|---|---|
| `event_id` | Unique ID |
| `schema_version` | Format version, so old records stay readable |
| `kind` | `session_start`, `user_message`, `assistant_message`, `tool_call`, `tool_result`, `file_change`, `verification`, `decision`, `goal`, `task`, `note`, `compaction`, `session_end`, `subagent_start`, `subagent_stop`, `capture_gap`, `import` |
| `session_id`, `parent_id` | Position in the historical tree |
| `writer_id`, `writer_seq` | Which process wrote it, and its order within that writer |
| `log_position` | Global order in the core log |
| `agent`, `agent_version`, `adapter_version` | Who produced it, with what |
| `occurred_at`, `recorded_at` | When it happened, and when it was stored |
| `payload_object` | Reference to the full raw content in the archive |
| `summary_fields` | Small structured fields used for indexing, such as tool name, path, or exit code |
| `completeness` | `captured`, `partial`, `unavailable`, or `imported` |
| `redactions` | Redaction records, never the redacted values |
| `idempotency_key` | Stops the same event being stored twice when hooks retry |
| `record_hash` | Hash over this record and the previous one in its chain |

### Completeness
- **Every event** carries a completeness level, and each session reports a summary of them.
- **Missing pieces are recorded too.** An adapter that can't see something, such as a file pulled in through `@` without a tool call, records an `unavailable` or `capture_gap` event instead of leaving a silent hole.
- **Imported history** (for example, an earlier transcript loaded later) is marked `imported`.
- **The active context shows incomplete capture**, so a partly captured session never looks complete.

---

## 5. Permanent core: event log and raw archive

### 5.1 Event log
- Append-only. Corrections are new events that reference the original.
- Each writer's records are hash-chained, so a missing or altered record is detectable.
- Writes are transactional; the agent never waits on a slow write (section 8.4).

### 5.2 Raw archive
- Every message, tool input, tool output, file version, and artifact is stored **in full**.
- Content is compressed, encrypted, and addressed by a keyed hash, so identical content is stored once.
- The database holds references and small metadata; the archive holds the bytes.
- Previews such as the first and last lines are derived and can be rebuilt. They never replace the original.

### 5.3 The only things withheld
| Withheld | What is recorded instead |
|---|---|
| Detected secrets | A redaction record with rule, location, and fingerprint, never the value |
| Paths you explicitly exclude, such as `.env` or key files | An exclusion record with path and hash |

Nothing else is truncated or sampled. If storage limits make full preservation impossible, the engine stops archiving and records a gap that names what was missed. It never silently keeps part.

### 5.4 Storage is a real constraint here
- Lossless memory grows without bound. Text and logs compress well, but a project generating large build logs or binary artifacts can still grow by gigabytes.
- **On this machine the WSL disk lives on C:, which had 5.8 GB free on 2026-11-06.** The store location must therefore be configurable, for example on another drive, and the engine must:
  - report the size of each project's store, and its growth rate;
  - warn at thresholds you set;
  - never delete anything automatically to make room.
- **The 400 MB figure is a RAM budget** for ADAM's running processes ([#33](https://github.com/AdamMostofi/ADAM/issues/33)). It is not a disk cap, and it never limits how much history the archive keeps.

---

## 6. Permanent core: structure

### 6.1 Historical tree
The tree is stored structure, not a view. Its node kinds:

```text
Project
 └─ Session (with its development path and git context)
     └─ Turn (one user request and everything done for it)
         └─ Event (message, tool call, tool result, file change, verification, decision...)
```

- **Edges between levels** are stored as `contains` relationships with order.
- **Session links:**
  - Resumed and forked sessions keep their parent session.
  - A session that builds on earlier work links back to the sessions it continues.
- **Navigation the engine must support:**

| From | To |
|---|---|
| Project | Its sessions, paths, goals, decisions |
| Session | Its turns and events, the paths it worked on, sessions it continued or forked from |
| Event | Files it affected, verifications it produced, what triggered it, what it caused |
| File | Every version, the events that changed it, tests that covered it |
| Decision | The discussion that produced it, evidence, alternatives, what replaced it |
| Verification | The exact code, environment, and command it tested |
| Path | Attempts, changes, outcome, the reason it was abandoned or chosen |

### 6.2 Development paths
A **development path** is one approach to a problem, for example "database: PostgreSQL" versus "database: SQLite". It is separate from git branches. A path can include conversation, experiments, and abandoned work that never reached a commit.

| Field | Meaning |
|---|---|
| `path_id`, `topic` | The question being solved, such as "database architecture" |
| `description` | The approach |
| `status` | `proposed`, `exploring`, `selected`, `abandoned`, `superseded`, `reconsidered` |
| `reason` | Why it was chosen, abandoned, or reconsidered |
| `alternative_to` | Other paths for the same topic |
| `evidence` | Links to events, changes, verifications, and decisions |
| `status_history` | Every status change, with time and source |

Changes and sessions carry a path and a role: `experiment`, `accepted`, or `reverted`.

#### How paths get recorded
The engine can't reliably detect a reasoning branch on its own, and the boundary rule forbids guessing. So paths come from three sources, and each is labelled:

| Source | Example | Label |
|---|---|---|
| Declared | The agent calls `mem_path`, or you run `amem path` | `declared` |
| Structural | A session fork, a new git branch, or a change that restores an earlier file version | `recorded`; this proposes a path but doesn't name it |
| Inferred | A later heuristic or model suggestion | `inferred`; shown as a suggestion until confirmed |

A plugin can encourage declaration, for example with an instruction to call `mem_path` before trying an alternative. The quality of path history therefore depends partly on the agent following that instruction, and the benchmark measures it.

### 6.3 Relationship graph
Any two records can be linked by a typed, directional edge.

| Field | Meaning |
|---|---|
| `from`, `to` | Any records: events, files, file versions, decisions, paths, goals, tasks, verifications, sessions, knowledge items |
| `type` | From the vocabulary below |
| `basis` | `recorded`, `declared`, or `inferred` |
| `source_event` | The event that created the edge |
| `retracted_by` | A later event that withdraws it; edges are never deleted |

**Vocabulary:**

| Group | Types |
|---|---|
| Structure | `contains`, `follows`, `part_of`, `references` |
| Causality | `triggered_by`, `caused_by`, `based_on`, `in_response_to` |
| Change | `modifies`, `modified_by`, `reverts`, `reverted_by` |
| Evidence | `verifies`, `verified_by`, `supports`, `contradicts` |
| History | `supersedes`, `superseded_by`, `alternative_to`, `selected_over`, `abandoned_because` |
| Code | `imports`, `depends_on`, `tests` |
| Planning | `blocks`, `blocked_by`, `advances` |
| General | `related_to` |

#### How each basis is used
- **`recorded`:** the engine observed it. Examples: a change happened in response to a message, a test ran on certain file versions, a file imports another.
- **`declared`:** an agent or user stated it. Example: "I changed `connection.py` because of the pooling failure in event 106."
- **`inferred`:** produced by a rule or a model, and always shown as inferred.

The engine records the time sequence automatically. It does not claim that one event *caused* another unless that was observed or declared. This keeps the boundary rule while still making debug chains like "change, tests failed, cause found, fix, tests passed" fully navigable.

### 6.4 Planning records
Goals, milestones, tasks, blockers, decisions, and progress notes are nodes in the same graph, created by `declared` events. Each keeps its own history.

| Record | Statuses |
|---|---|
| Goal | `active`, `achieved`, `dropped` |
| Task | `open`, `in_progress`, `done`, `blocked`, `cancelled` |
| Decision | `proposed`, `active`, `superseded` |
| Blocker | `open`, `resolved` |

Agent-declared decisions start as `proposed` unless they came directly from a user message.

---

## 7. File history, code graph, and verification

### 7.1 File history
- Every observed version of every file: path, content hash, archive reference, size, git blob and commit when tracked, and renames.
- Each version links to the event that produced it and its development path.
- Uncommitted versions are kept, so work between commits can be recovered.

### 7.2 Code dependency graph
- Imports and references are extracted with tree-sitter, starting with Python and TypeScript.
- **Updated incrementally:** only files whose hash changed are re-parsed.
- Stored as derived `imports` and `depends_on` edges, so it can be rebuilt.
- Used for:
  - showing what a change may affect;
  - choosing the relevant files for a verification;
  - relevant-file maps in the active context.
- Languages without a parser fall back to file-level history only, and say so.

### 7.3 Verification records
A verification stays historically true forever. Its *current* status is computed.

| Field | Example |
|---|---|
| `verification_id` | `1042` |
| `result`, `exit_code` | `passed`, `0` |
| `command` | `pytest tests/auth/` |
| `check_type` | `test`, `build`, `lint`, `custom` |
| `commit`, `branch`, `worktree`, `dirty` | `abc123`, `feature/auth`, `~/proj`, `yes` |
| `tree_hash` | Hash of the whole working tree |
| `relevant_files` | Path and hash for each relevant file, such as `auth.py`, `jwt.py`, `users.py` |
| `relevance_method` | `import_closure`, `coverage`, or `whole_tree` |
| `environment` | Interpreter versions, OS, lockfile hashes, dependency list hash, and the names of relevant environment variables (never their values) |
| `output_object` | The full output |
| `occurred_at` | Timestamp |

**Relevant files** come from coverage data when available. Otherwise they come from the test's import closure in the dependency graph. Otherwise the whole tree is used, marked `whole_tree`, so status is conservative.

**Current status:**

| Status | Meaning | Reasons recorded |
|---|---|---|
| `verified` | All relevant files and the environment match | None |
| `stale` | Something relevant changed | For example: `jwt.py changed in event 2210`, `Python 3.12 -> 3.13`, `lockfile changed` |
| `unknown` | It can't be checked, for example after a failed reconciliation | The cause |

---

## 8. Reconciliation, recovery, and concurrency

### 8.1 Reconciliation
1. **List files** with `git status --porcelain=v2` and `git ls-files -co --exclude-standard`; non-git folders use an ignore-aware walk.
2. **Skip unchanged files** by size and mtime, with a periodic full hash.
3. **Check `HEAD`** for moves, using reflog to describe pulls, resets, rebases, and checkouts.
4. **Attribute each difference** as `agent_tool`, `agent_bash`, `external`, `git_operation`, or `unattributed`. It never guesses.
5. **Record a change** for each difference, including deletes and renames, and update file history.
6. **Batch large git operations** that touch hundreds of files into one group record, with every file still listed.
7. **Mark dependents for re-evaluation:** the code graph, verifications, and active context items.

Reconciliation runs:
- at session start;
- after shell commands and edit batches;
- before state queries;
- on demand.

If it fails, state becomes `unknown`.

### 8.2 Checkpoints and replay
- **The event log is the truth.** Everything else is rebuilt by replaying it.
- **A checkpoint** records:
  - a log position;
  - the chain hashes up to that position;
  - a snapshot of the derived layer and active context.
- **When checkpoints happen:** at session end, every N events, and before large reconciliations.
- **Recovery:**
  1. Load the newest checkpoint that passes integrity checks.
  2. Replay events after it.
  3. Reconcile against the files and git.
  4. Record the recovery itself as an event.

### 8.3 Integrity
`amem verify` checks:
- record chains;
- archive object hashes;
- references to missing objects or records;
- checkpoint validity.

Results are reported; nothing is repaired silently. `amem rebuild` regenerates the derived layer.

### 8.4 Failure scenarios

| Situation | What happens |
|---|---|
| Windows crash or power loss | SQLite durability plus a write spool; next start replays from the last checkpoint and reconciles |
| Agent closes unexpectedly | Open change records stay `intended`; reconciliation resolves them from file hashes |
| Agent edits but crashes before reporting | Reconciliation finds the change and attributes it as well as it can |
| Large git operation | Batched record; affected verifications go `stale` |
| Corrupted index | Detected by `amem verify`; rebuilt from the core |
| Corrupted core record | Reported with location; never silently dropped; restore from backup or record the loss |
| Memory engine itself fails | Capture fails open: the agent continues, and a gap is recorded |

### 8.5 Several agents at once
- **Each agent session is its own writer** with its own sequence. SQLite serializes the writes, so no writer overwrites another.
- **Every change keeps its own before-hash.** If agent B's before-hash doesn't match what agent A just wrote, the engine records a **conflict** event linking both changes. It never merges or overwrites.
- **The active context shows open conflicts** until someone resolves them with a declared event.
- **Separate git worktrees per agent** remain the recommended setup. They give clean attribution, and the engine tracks state per worktree.

---

## 9. Active context

### 9.1 Sections
Each section can be fetched on its own, and each item can be expanded to its evidence.

1. **Project status:** branch, `HEAD`, dirty files, open conflicts, capture completeness.
2. **Objectives:** active goals and milestones.
3. **Current progress:** progress notes, and recently completed and accepted changes.
4. **Current tasks and next steps.**
5. **Blockers and known problems:** open blockers, latest failing checks, unresolved errors.
6. **Architectural decisions:** active decisions with their paths and alternatives.
7. **Development paths:** open, selected, and recently abandoned approaches.
8. **Relevant files:** a file map focused on the current task, from the code graph and recent changes.
9. **Historical references:** the sessions and events most related to the current work.
10. **Verification:** each area marked `verified`, `stale`, or `unknown`, with reasons.

Every item shows its source (`recorded` or `declared`), its age, and its staleness. Declared items go stale when the files they name change, or when a configurable age passes.

### 9.2 Levels

| Level | Contains | Delivered |
|---|---|---|
| 0 | A tiny overview: project status line, top objective, counts of stale items, conflicts, and blockers | Injected at session start |
| 1 | Objectives, progress, tasks, next steps, blockers | Injected at session start, within the configured budget |
| 2 | Decisions, paths, relevant file map, verification summary | On request, per section |
| 3 | Specific events, messages, file versions, verification records | On request, by ID or search |
| 4 | Full original sessions, raw outputs, artifacts | On request, paged |

**Budgets are settings, not architecture.** The defaults suit a small model, for example a 4B local model. A larger model can be given more at session start.

**Focus:** levels 1 and 2 are ordered by relevance to the current work, meaning the files and paths named in the prompt, the active development path, and recent changes. Agents working on one function don't receive the whole project's file map.

### 9.3 Explicit updates
Agents and users can update planning records directly:
- `mem_goal`, `mem_task`, `mem_blocker`, `mem_progress`, `mem_decide`, `mem_path`;
- the same through `amem` commands.

Each update is a `declared` event, so its history is kept.

---

## 10. Retrieval interface

### MCP tools
| Tool | Purpose |
|---|---|
| `mem_context(section, level)` | Active context sections |
| `mem_tree(node, depth)` | Navigate the historical tree |
| `mem_node(id)` | One record with its edges |
| `mem_trace(id, types, direction, depth)` | Follow relationships, such as the causal chain behind a change |
| `mem_paths(topic)` | Development paths and their history |
| `mem_file_history(path)` | Versions, changes, and verifications for a file |
| `mem_verifications(scope)` | Verification records and current status |
| `mem_search(query, filters)` | Exact and full-text search |
| `mem_get(id)` | Raw original content, paged |
| `mem_goal`, `mem_task`, `mem_blocker`, `mem_progress`, `mem_decide`, `mem_path` | Explicit updates |

### Rules
- **Few tools by default:** retrieval tools load on demand where the agent supports it, to keep per-turn context cost low.
- **Sources on everything:** every result includes record IDs, timestamps, completeness, and, for state, current status.
- **Old content is labelled as historical** and never presented as current.
- **Data, not instructions:** retrieved content is labelled as data. The injected context contains only engine-generated fields and declared planning items, never raw tool output, so stored text can't act as instructions in a later session.

### Also available
- **CLI:** `amem status`, `context`, `tree`, `trace`, `search`, `get`, `verify`, `rebuild`, `reconcile`, `checkpoint`, `purge`, `export`, `path`, `goal`, `task`.

---

## 11. Secrets and deletion

### Before storing
- **Scanning:** every payload is checked with Gitleaks-style rules plus entropy checks before anything is written.
- **Replacing:** each match becomes `[SECRET:<rule>:<fingerprint>]`, and a redaction record is stored.
- **Excluded paths:** their content is never stored.

### At rest
- **Encryption:** AES-256-GCM, with a key per session wrapped by a project key.
- **Key storage:** the OS keychain, or a passphrase on WSL (decision D4).
- **Object IDs:** keyed hashes, so an ID can't confirm a guessed value.
- **The search index:** in the first build it stays readable on disk, protected by file permissions, excluded from backups, and rebuilt after any purge.

### Purging a leaked secret
1. Add the value's fingerprint to a deny list.
2. Find every affected object.
3. Write redacted replacements and leave tombstones.
4. Delete the original content.
5. Rebuild the index.
6. Checkpoint, compact, and `VACUUM` the database.
7. Rotate the encryption key.
8. Log what was purged, without the value.

History stays connected, and the purge itself is an event.

### Limits
- **Rotate the secret anyway.** Removal from the store is not revocation.
- **Other copies may survive** in the agent's own transcript, shell history, disk snapshots, sync folders, or old backups.
- **Encryption mainly protects against stolen disks and backups,** not against malware running as you.

---

## 12. Testing and benchmark

### 12.1 Engine tests (no model needed; run in CI)

| Area | Pass condition |
|---|---|
| Capture | Replayed sessions store every event or a recorded gap; completeness is correct |
| Lossless | A 50,000-line output is retrievable byte for byte |
| Tree | Every navigation in 6.1 works on fixtures |
| Paths | Declared, structural, and inferred paths keep correct labels and status history |
| Relationships | Edges are never deleted; retractions are honoured; `inferred` is always labelled |
| Code graph | An edit re-parses only changed files; affected-file results match fixtures |
| Verification | Each recorded reason (file, environment, lockfile) flips status to `stale` correctly |
| Reconciliation | All seeded external edits and git operations are labelled correctly |
| Recovery | Killed at random points, recovery from checkpoint plus replay matches a clean replay |
| Integrity | Corrupting a record, object, or checkpoint is detected and reported |
| Concurrency | Two writers changing one file produce a conflict record, never an overwrite |
| Context | Section budgets are honoured, and focus selects the right files |
| Secrets | Detectable canaries appear nowhere in raw bytes; purge removes a planted secret |
| Injection | Tool output containing instructions never reaches injected context |

### 12.2 Agent benchmark (stage 3.2)

**Arms:**
- **A:** native compaction only.
- **B:** git, grep, and a well-kept notes file. **This is the strong baseline to beat.**
- **C:** this engine.

**Scenarios** run across several sessions on fixture repos:

| Type | Example |
|---|---|
| Recall | "Why did we choose X?" |
| Stale state | You edit a file between sessions |
| Replaced decision | Session 3 must follow the decision made in session 2 |
| Abandoned path | "Did we try SQLite? Why did we drop it?" |
| Reconsidered path | An abandoned approach becomes relevant again |
| Causal debugging | Rebuild the chain from change, to failure, to cause, to fix |
| False success | Tests passed, then code or the environment changed |
| Crash | Continue correctly after a forced kill mid-change |
| Two agents | Continue in OpenCode after work in Claude Code (needs 3.3, so it runs in the repeat after 3.3) |
| Unknown | The answer isn't in history |
| Long history | Ask the same questions after more than 32K tokens of unrelated work |

**Metrics:**
- recall accuracy;
- stale-state errors;
- false claims;
- false "don't know" answers;
- task success;
- tokens;
- time;
- storage growth;
- hook latency;
- RAM;
- how often the agent declared paths when instructed.

**Method:**
- Write the gold answers and thresholds before any runs.
- Do at least 5 runs per scenario per arm, and report the spread.
- Publish all fixtures and raw results.

**Decision rule** (unchanged in spirit):

| Result | Action |
|---|---|
| Go | At least 50% fewer stale-state errors than both baselines, recall no worse than B, and tokens within +10% of B: continue with the remaining plugins |
| Ties B | Narrow the scope |
| Loses | Stop the plugin work |

In every case, ADAM keeps the core.

---

## 13. Plugins for coding agents

### How plugins connect
```text
Claude Code event --.
OpenCode event -----+
Pi event -----------+--> adapter --> canonical event --> engine core
Codex event --------+
Other agent event --'
```

- **One core:** `amem` is installed once. Each plugin only maps its agent's events to the canonical format (section 4) and installs the hooks and MCP configuration.
- **Shared memory:** all agents share one project store, so work can continue across agents.
- **No logic in plugins:** if an adapter needs logic beyond mapping, the canonical format is wrong and gets fixed.
- **A shared suite:** recorded events from every agent run through one adapter test suite.

### Support by agent
Taken from each agent's docs on 2026-11-06. Stage 3.5 publishes a table tested against specific versions.

| Agent | Stage | Package | Capture | Context at session start |
|---|---|---|---|---|
| Claude Code | 3.1 | Plugin: `.claude-plugin/plugin.json`, `hooks/hooks.json`, `.mcp.json` | Tool, prompt, stop, compaction, and subagent hooks | `SessionStart` `additionalContext` |
| OpenCode | 3.3 | npm plugin in `opencode.json` | `tool.execute.before/after`, `file.edited`, message and session events | **To verify:** docs show injection at compaction; fallback is a `mem_context` call |
| Pi | 3.4 | Pi package (`pi install`) | `tool_call`, `tool_result`, session and compaction events | `session_start` or `context` event |
| Codex | 3.5 | `.codex-plugin/plugin.json` with hooks; trust review needed | Tool, prompt, stop, compaction hooks | `SessionStart` |
| Gemini CLI | 3.5 | Extension; **check status**, as some tiers moved to Antigravity CLI | `BeforeTool`, `AfterTool`, agent and compression hooks | `SessionStart` `additionalContext` |
| Cursor | 3.5 | `hooks.json` or plugin hooks | Tool, edit, shell, and compaction hooks | `sessionStart`, **fire-and-forget, so test the timing** |
| MCP-only tools | 3.5 | `amem setup <agent>` after checking official docs | None assumed | A rule asks the agent to call `mem_context` |
| Tools with neither | 3.5 | CLI only | File reconciliation only | Manual |

### Support tiers

| Tier | Requires | Gets | Completeness shown |
|---|---|---|---|
| Full | Lifecycle hooks | Everything | Per event |
| Partial | MCP | Retrieval, planning updates, file reconciliation | Conversation `unavailable`; changes `unattributed` |
| Minimal | A shell | File reconciliation, manual lookups | Mostly `unavailable` |

### Development and release
- **During development:** the engine lives in `packages/agent-memory/` and the plugins in `plugins/`, inside `~/ADAM`. CI fails if the engine imports ADAM.
- **At stage 3.6:**
  - Extract both to their own repo with `git subtree split`.
  - Publish the CLI, npm, Pi and Gemini packages, a Claude Code marketplace, and Codex packaging.
  - ADAM then pins a released version and drops its in-repo copy.

---

## 14. How ADAM uses it (Phase 4)

**The engine stores and connects. ADAM decides what to believe.**

| ADAM need | Engine building block |
|---|---|
| Books and passages | Raw archive and file history |
| Proof records | Relationship edges with `recorded` basis |
| Thought traces | Events, the tree, and causal edges |
| Study sessions | Sessions and turns |
| Abandoned and selected lines of reasoning | Development paths |
| Tool audit | The event log |
| Rule and skill versions | Versioned records |

**Stays in ADAM:** logic rules, inference, claim review, ontology, skill lifecycle, and fact meaning.

### The boundary
- `memory/engine_store.py` is ADAM's only link to the engine, and the kernel never imports it.
- ADAM uses the engine as a library. No hooks or agents are involved.
- ADAM must stay within its RAM budget. The archive's disk size is a separate matter.
- Stage 4.1 depends only on the core, so it works whatever stage 3.2 decides.

---

## 15. Roadmap (Phases 2 and 3)

| Stage | Name | Delivers |
|---|---|---|
| 2.1 | Prove the Reconciler | A throwaway spike testing change detection, attribution, and replay-from-checkpoint |
| 2.2 | Seal the Archive | Canonical event format, completeness, append-only log with hash chains, full content-addressed raw archive, encryption, secret redaction records |
| 2.3 | Grow the Tree | Historical tree, relationship graph with labelled sources, development paths, planning records |
| 2.4 | Map the Code | File history, incremental code dependency graph, verification records with environment fingerprints and stale reasons |
| 2.5 | Survive the Crash | Reconciliation, checkpoints, replay, `amem verify`, concurrency conflicts |
| 2.6 | Open the Archive | Active context sections and levels, focus selection, search, MCP tools, CLI |
| 2.7 | Burn the Leak | Purge, storage reporting, and the full engine test suite in CI |
| 3.1 | First Plugin | Claude Code adapter onto the canonical format; first real use |
| 3.2 | Weigh the Thesis | The agent benchmark on the complete core; go or no-go |
| 3.3 | OpenCode Plugin | OpenCode adapter; shared memory across agents |
| 3.4 | Pi Extension | Pi adapter; maps Pi's session tree |
| 3.5 | Other Agents | Codex, Gemini CLI, Cursor, MCP-only and CLI-only tiers |
| 3.6 | Release the Engine | Own repo, packages, marketplaces |

### What revision 2 changes in the roadmap
- One new stage (2.7).
- A larger scope for stages 2.2 to 2.6.
- The code dependency graph moves from "after the benchmark" into 2.4, because verification depends on it.
- The benchmark now tests the complete core.

### Kept out of scope
- AI summaries and similarity search, until after the benchmark.
- Cloud sync.
- A UI.

---

## 16. Risks

| Risk | Mitigation |
|---|---|
| Scope grows into a huge project | Phases 2 and 3 stay sequential; each stage has acceptance criteria; summaries and similarity search stay out |
| Disk fills up | Configurable location, size reporting, warnings, never silent deletion |
| Agents don't declare paths or causes | Plugin instructions, measured in the benchmark; structural signals still recorded |
| Inferred links mistaken for facts | Basis shown everywhere; inferred items never enter injected context as facts |
| Hook latency | Measured in 3.1; move hot paths to compiled helpers if needed |
| Context too large for a small model | Levels and budgets as settings; focus selection; tested with small budgets |
| Agent hook APIs change | Thin adapters, version checks, completeness records |
| False `verified` status | Strict relevance rules, with `whole_tree` fallback and `unknown` on any doubt |
| Prompt injection replayed from memory | Raw output never injected; results labelled as data |
| Git plus notes is good enough | Arm B can stop plugin expansion early |

---

## 17. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | First agent | **Decided 2026-11-09:** Claude Code, then OpenCode, then Pi |
| D2 | Language | Python for the prototype; compiled helpers only if measured latency requires them |
| D3 | Store location | **Open.** Recommend a user data directory per project, configurable to another drive because of C: free space |
| D4 | Key storage | OS keychain, with a passphrase fallback on WSL |
| D5 | Default capture | **Revised:** everything in full except secrets and explicit exclusions |
| D6 | Benchmark budget | Agent runs cost API money; start with one model |
| D7 | Open source | Public at release, MIT, with benchmark data public |
| D8 | Name | Choose before 3.6. The working name is `agent-memory`; the architecture name is "Lossless Tree Memory Engine" |
| D9 | Path declaration | **New:** how strongly plugins prompt agents to declare paths and causes. Recommend a light instruction, then measure |

---

## 18. Sources

- LCM paper: <https://arxiv.org/html/2605.04050v1>
- pi-lossless: <https://pi.dev/packages/pi-lossless?page=96>
- hermes-lcm: <https://hermesatlas.com/projects/stephenschoettler/hermes-lcm>
- CMV paper: <https://arxiv.org/html/2602.22402v1>
- Letta MemFS: <https://docs.letta.com/concepts/memfs>
- Graphiti and Zep summary: <https://www.emergentmind.com/papers/2501.13956>
- Pi internals: <https://pi.dev/docs/latest/how-pi-works.md>
- Pi extensions: <https://pi.dev/docs/latest/extensions>
- Claude Code hooks: <https://code.claude.com/docs/en/hooks>
- Claude Code plugins: <https://code.claude.com/docs/en/plugins>
- OpenCode plugins: <https://opencode.ai/docs/plugins/>
- OpenCode MCP: <https://opencode.ai/docs/mcp-servers/>
- Codex hooks: <https://learn.chatgpt.com/docs/hooks>
- Gemini CLI hooks: <https://geminicli.com/docs/hooks/reference/>
- Gemini CLI extensions: <https://geminicli.com/docs/extensions/>
- Cursor hooks: <https://cursor.com/docs/agent/hooks>
- SQLite VACUUM: <https://www.sqlite.org/lang_vacuum.html>
- SQLite secure delete and WAL (secondary): <https://antonz.org/sqlite-secure-delete/>
- Crypto-shredding (vendor overview): <https://www.conduktor.io/glossary/crypto-shredding-for-kafka>
- Aider repo map (secondary): <https://kitemetric.com/blogs/how-aider-indexes-your-codebase-for-ai-powered-code-assistance>
