# Agent Memory Engine: Design Spec and Test Plan

**Status:** Proposed and scheduled. Nothing here is built or measured. Work order: [ROADMAP.md](../ROADMAP.md), Phases 2 to 4.
**Date:** 2026-11-06
**Working title:** Agent Memory Engine ("the engine"). The final name is decision D8.
**Relationship to ADAM:** A standalone product developed inside the ADAM repo until release. ADAM uses it through one interface ([#46](https://github.com/AdamMostofi/ADAM/issues/46)), and the engine never imports ADAM code.

All latency, size, and score numbers below are proposed targets, not results.

---

## 1. The idea in brief

Coding agents lose context when sessions compact or end. Several projects now solve that by keeping full history and retrieving from it. Those projects mostly answer: **"What happened?"**

This engine also answers: **"What is true right now, and how do we know?"**

A perfect transcript can still mislead an agent. The transcript says `auth.py` uses JWT and that tests passed. Since then, you edited the file, ran `git pull`, and reverted a decision. A memory system that retrieves the old statement confidently is worse than one that says it doesn't know.

**The product thesis to test:** an agent using verified, reconciled project state makes fewer stale-state errors than one using native compaction or plain git and grep, without costing more tokens.

If the benchmark in section 11 does not show that, the differentiator is not real, and the project should narrow or stop.

### Core rules

1. **Capture happens at the agent boundary.** The agent does not maintain its own memory files.
2. **The filesystem and git are the truth about code.** The engine records observations of them and never overrides them.
3. **State is computed when read.** It is not a document someone must remember to update.
4. **Every state claim carries evidence and a status:** `verified`, `stale`, or `unknown`.
5. **Summaries and indexes are disposable caches.** Each points back to its source objects, and each can be rebuilt.
6. **History is immutable, except for one audited operation:** removing leaked secrets.

---

## 2. Scope

### MVP
- One agent adapter (recommended: Claude Code, decision D1).
- Automatic capture of sessions, messages, tool calls, and file changes.
- Immutable, encrypted object storage.
- A change ledger with verification results.
- Reconciliation against the real filesystem.
- A computed project-state view with staleness flags.
- Exact indexes and full-text search.
- Progressive retrieval through a CLI and MCP tools.
- Secret scanning, redaction, and purge.
- An engine-level replay benchmark, followed by an agent-level benchmark.

### After the benchmark, only if it passes
- Symbol and dependency indexes.
- Summaries with lineage.
- A second adapter (Pi), to prove the core is agent-neutral.
- A library API for ADAM.

### Non-goals
- Rebuilding git, or storing committed history it already holds.
- Semantic search in the MVP. It may be added later as a supplement, never as the source of truth.
- Deciding whether a statement in history is correct. The engine tracks evidence, not truth about the world.
- Cloud sync or multi-user sharing.
- Replacing an agent's own transcript or compaction.

### What "lossless" means here

| Data | Treatment |
|---|---|
| User and assistant messages | Stored whole, unless a secret is redacted |
| Tool inputs and outputs | Stored whole, up to a size limit (proposed 10 MB per payload) |
| Payloads over the limit | Head, tail, length, and hash stored, and explicitly marked `truncated` |
| Uncommitted file contents at each edit | Stored, within the same size limit |
| Committed file history | Referenced through git, not copied |
| Binary files | Hash and size only, by default |
| Excluded paths such as `.env` and key files | Hash only, never content |
| Detected secrets | **Deliberately not stored.** Replaced by a placeholder |

So "lossless" is a precise promise with listed exceptions. The system must never silently drop data: anything not stored whole is marked.

---

## 3. Architecture

```text
 Agent (Claude Code, later Pi, ADAM...)
   |  hooks / extension events            ^ brief + MCP tools
   v                                      |
 Adapter: normalizes events        Retrieval (levels 0-3)
   |                                      ^
   v                                      |
 Ingest: secret scan -> redact -> compress -> encrypt
   |                                      |
   v                                      |
 Core store (truth)                 State view (computed on read)
  - objects (immutable)                   ^
  - events (history tree)                 |
  - changes + verifications          Reconciler <--- filesystem + git
  - decisions
   |
   v
 Derived store (disposable): full-text, symbols, summaries
```

### Storage layout

This is the engine's data at runtime, not its source code, which section 16 covers.

```text
<user-data-dir>/agent-memory/<project-id>/
  core.db          # events, ledger, decisions, object metadata
  objects/ab/cd... # encrypted payloads
  derived/index.db # full-text and symbols; safe to delete
  spool/           # encrypted fallback when core.db is busy
```

- **Location:** outside the project repo, so memory can't be committed by accident (decision D3). On WSL this still uses the virtual disk on C:, so size limits matter.
- **Sync folders:** the engine refuses, or warns loudly about, a store inside a synced folder. This matters on your machine, because your Windows Desktop is in OneDrive.
- **Project ID:** from the repo's root commit plus a user-assigned name, so moving the folder doesn't lose memory. Non-git folders get a generated ID stored outside the project.
- **Worktrees and branches:** history is per project, while state is per worktree and `HEAD`.

### Technology
SQLite and FTS5 for storage and search, with stdlib-only hashing. Python for the prototype (decision D2), with no resident daemon. Each hook is a short process and the MCP server runs only during a session.

---

## 4. Capture at the agent boundary

### Normalized events
Adapters translate agent-specific events into:

`session_start`, `user_message`, `assistant_message`, `tool_pre`, `tool_post`, `tool_failed`, `compaction`, `session_end`, `subagent_start`, `subagent_stop`.

Each event has a parent, which forms the history tree. Resumed and forked sessions become branches.

### Claude Code mapping

| Engine event | Claude Code hook | Notes |
|---|---|---|
| `session_start` | `SessionStart` | Runs reconciliation, then returns the brief through `additionalContext` |
| `user_message` | `UserPromptSubmit` | |
| `tool_pre` | `PreToolUse` | Receives `tool_name`, `tool_input`, `tool_use_id`. Records the before-hash for `Write` and `Edit` |
| `tool_post` | `PostToolUse` | Adds `tool_response` and `duration_ms` |
| `tool_failed` | `PostToolUseFailure` | |
| `assistant_message` | `Stop` | Docs say the transcript may lag, so use `last_assistant_message` here |
| `compaction` | `PreCompact` | Snapshots the transcript before compaction |
| `session_end` | `SessionEnd` | The default budget is only 1.5 s, so this does a best-effort flush and nothing heavy |
| Subagent events | `SubagentStart`, `SubagentStop` | |

### Rules for capture
- **Fail open.** A memory failure must never block the agent. Hooks do not use blocking failure modes. Any gap is recorded as a `capture_gap` event and shown in the brief.
- **Transcript as a backstop.** Hook data is primary. The raw transcript is also stored as an opaque object at compaction and session end, and it can fill gaps. Its format is treated as unstable, so parsing is version-gated and best-effort.
- **Known blind spots.** `@`-referenced files arrive without a tool call, so no `PreToolUse` fires for them. Bash can change any file without naming it. Reconciliation (section 6) covers these, which is why it exists as a separate mechanism.
- **Speed target:** hook p95 under 100 ms for normal payloads. If Python startup makes this impossible, that feeds decision D2.
- **Normalize paths.** Docs note Windows paths use backslashes, and you work across Windows and WSL.

---

## 5. The change ledger

### Why a transaction can't be literal
A filesystem edit and a database write cannot be one atomic transaction, and the agent can crash between them. So each change is a record that moves through states:

`intended` -> `applied` | `failed` | `unknown`

`PreToolUse` writes `intended` with the before-hash. `PostToolUse` checks the actual file and writes the outcome. A crash leaves `intended`, and the next reconciliation resolves it by comparing hashes.

### The change record

| Field | Source |
|---|---|
| `change_id` | Generated |
| `path` | Tool input or reconciliation |
| `before_hash`, `after_hash` | Computed from file bytes, never reported by the agent |
| `before_object`, `after_object` | Stored content, so uncommitted states can be recovered |
| `git_blob_before`, `git_blob_after` | When tracked; optional cross-reference |
| `timestamp` | Engine clock |
| `actor` | `agent_tool`, `agent_bash`, `external`, `git_operation`, or `unattributed` |
| `reason`, `reason_source` | `stated` if the user or agent said why, otherwise `inferred` from the nearest user request; may be empty |
| `message_event_id` | The user message that led to it |
| `task_id` | Optional |
| `tool_use_id` | When caused by a tool |
| `verification_id` | The latest check covering this exact tree state, if any |
| `status` | `intended`, `applied`, `failed`, `unknown` |

**Why `reason` can be inferred or empty:** requiring the agent to explain each edit would add tokens and make it a memory maintainer again. An honest empty reason beats an invented one.

### Git covers less than it seems
Git holds committed history, but work between commits is often what you need to recover. So the ledger stores uncommitted before and after contents, and uses git for anything committed. This keeps the "use git" rule without losing uncommitted work.

### Verification records

| Field | Meaning |
|---|---|
| `verification_id` | Generated |
| `command` | Stored as a scanned object |
| `exit_code` | From tool output |
| `output_object` | Full output |
| `tree_hash` | Hash of the working tree when the check ran |
| `check_type` | `test`, `build`, `lint`, or `custom` |

Commands are classified using configurable patterns, such as `pytest` or `npm test`. A pass means: **this command passed on this exact tree.** It does not mean the code is correct, and the brief never says so.

---

## 6. Reconciliation

Reconciliation compares what the engine last knew with what is on disk now. It is the core differentiator.

### When it runs
- At session start, before the brief.
- After each Bash tool call, and after each batch of edits.
- Before answering state and history queries, in a fast form.
- At session end, only if it fits the time budget.
- On demand: `agent-memory reconcile`.

### Steps
1. **List files:** use `git status --porcelain=v2` and `git ls-files -co --exclude-standard`. Non-git folders use a directory walk with ignore rules.
2. **Find changes fast:** skip files whose size and mtime are unchanged, except for a periodic full hash.
3. **Hash candidates** using the engine's own hash of raw bytes.
4. **Check `HEAD`:** a moved `HEAD` or changed branch produces a `git_operation` event. Reflog helps describe it (pull, reset, rebase, checkout).
5. **Attribute each difference:**
   - Matches a pending agent change: complete that record.
   - Occurred during a Bash call: `agent_bash`, linked to that command.
   - Explained by a `HEAD` move: `git_operation`.
   - Otherwise: `external`, or `unattributed` when parallel activity makes it ambiguous.
6. **Write a change record** for each difference, including deletes and renames.
7. **Invalidate dependents:** symbols, verifications, and state items tied to the old hash.

### Hard rules
- Reconciliation never edits project files.
- An unattributed change is reported as unattributed. The engine does not guess.
- Failure to reconcile makes state `unknown`, not `verified`.
- Parallel agents in one worktree can make attribution ambiguous. Separate worktrees are the supported way to get clean attribution.

---

## 7. State: computed, not maintained

The original design has `project_overview.md`, `current_progress.md`, and similar documents. **That approach would recreate the staleness problem.** Instead, documents are generated on read, and each item is tied to its evidence.

| State item | Where it comes from |
|---|---|
| Branch, `HEAD`, dirty files | Git, read live |
| File map, symbols | Generated from code |
| Changes since last session | Ledger plus reconciliation |
| Last test result | Verification records, compared with the current tree |
| Active decisions | Decision records |
| Goals and next steps | Written by a user or agent, because code can't reveal them |
| Open failures | The latest failed check on the current tree |

### Status rules

| Status | Meaning | Example |
|---|---|---|
| `verified` | Evidence still matches the current tree | Tests passed on this exact `tree_hash` |
| `stale` | Evidence exists but something it depends on changed | Tests passed, then `auth.py` changed |
| `unknown` | No evidence, or a check couldn't run | Reconciliation failed |

Each item records its dependencies, such as `{path, hash}` pairs, a `tree_hash`, or a decision ID. Status is worked out when read. Goals and next steps can only ever be `stated`, along with when and by whom, and they go stale when the files they name change or the set age passes.

### Decisions

Decisions can't be derived from code, so they are the one thing written deliberately.

| Field | Meaning |
|---|---|
| `decision_id`, `text`, `reason` | The decision and why |
| `source_event_id` | Where it came from |
| `author` | `user` or `agent` |
| `status` | `proposed`, `active`, or `superseded` |
| `valid_from`, `valid_to` | When it applied, plus when it was recorded |
| `superseded_by` | The replacing decision |
| `applies_to` | Optional paths or symbols |

The agent records one with `mem_decide` only when a choice is actually made. Agent-recorded decisions start as `proposed` unless they came directly from a user message. Automatic detection is deferred because false positives would pollute the most trusted data.

---

## 8. Retrieval

Each level costs more than the one before, and the model starts at the lowest.

| Level | Tool | Returns | Proposed cost |
|---|---|---|---|
| 0 | Brief, injected at session start | Branch and `HEAD`, dirty files, external changes since last session, last check result with status, active decisions, goals, capture gaps. Every line has an ID | 500 tokens or fewer |
| 1 | `mem_search`, `mem_history`, `mem_decisions`, `mem_state` | Short hits with IDs | Capped, paged |
| 2 | `mem_get(id)` | One exact object: a message, diff, snapshot, or output | Capped per call |
| 3 | `mem_expand(branch or range)` | Original records for a range | Paged, with a hard cap |

### Choosing the right index

| Question | Answered from |
|---|---|
| What's the current status? | State view |
| What changed while I was away? | Reconciliation and ledger |
| What did this file look like before? | Git, then ledger snapshots |
| Why did we choose JWT? | Decisions, then full-text search |
| What did we decide three days ago? | History with time filters |
| Where is this function? | Symbols (later), `git grep` until then |
| What depends on this function? | Dependency graph (later) |

### Rules
- Every result carries its source ID and timestamp. If it describes state, it carries status too.
- **Retrieved content is data, not instructions.** Stored tool output can contain text aimed at a model, and memory would replay it in later sessions. So the brief contains only engine-generated fields and short user or agent statements, never raw tool output. MCP results label historical content clearly.
- Brief wording is factual rather than imperative, as Claude Code's docs recommend for injected context.
- Retrieved history must not be presented as current state. A hit about a file shows whether that file has changed since.

---

## 9. Derived data

- Everything in `derived/` can be deleted. `agent-memory rebuild` recreates it from core data.
- **Deterministic items** (full-text, symbols) must rebuild to equivalent results, and this is tested.
- **LLM summaries, when added:** stored with source object IDs, model, prompt version, and time. Regenerating one may produce different text, which is fine, because a summary is never evidence.
- **A summary can't support a state claim.** Only source objects, file hashes, and verification records can.
- The MVP has **no LLM summaries**, so the engine needs no model or API key.

### Retention
Core objects are kept unless purged. Size is watched, not assumed to be small. ADAM's vector store reached about 1.4 GB from 5,401 rows, so growth is a measured benchmark item. Limits apply to tool output and derived data, and old compressed objects can be moved to archive storage.

---

## 10. Secrets and deletion

Immutability and secrets conflict. Agent logs routinely contain tokens, and comparable tools are open about the limits: [pi-lossless](https://pi.dev/packages/pi-lossless?page=96) stores plaintext SQLite and describes redaction as best-effort, and [hermes-lcm](https://hermesatlas.com/projects/stephenschoettler/hermes-lcm) has sensitive-pattern redaction off by default and doesn't rewrite existing rows. This is an area the engine can do better, though no scanner catches everything.

### Layer 1: Don't store them
Every payload is scanned **before** anything is written.
- Detection uses Gitleaks-style rules plus entropy checks, with custom patterns allowed.
- A match is replaced by `[SECRET:<rule>:<fingerprint>]`. The original is not kept anywhere.
- The fingerprint is a keyed hash, so repeats can be matched without revealing the value.
- Excluded paths like `.env`, `*.pem`, and `id_*` are stored as hash only.

### Layer 2: Encrypt what's stored
- **Object encryption:** AES-256-GCM. Each session gets its own data key, wrapped by a project key.
- **Project key:** in the OS keychain where available. WSL often has none, so the fallback is a passphrase or a protected key file (decision D4).
- **Object IDs:** keyed hashes (HMAC-SHA-256) of plaintext, not plain hashes, so an ID can't confirm a guessed value. Deduplication is per project. Git blob IDs are stored separately for tracked files only.
- **Compression** happens before encryption.

### What encryption doesn't cover
A full-text index needs readable tokens. So `derived/index.db` is plaintext in the MVP, protected by file permissions, excluded from backups, and rebuilt on purge. An encrypted database such as SQLCipher is an optional later step. This also protects mainly against stolen disks, stray backups, and sync. **It does not protect against malware running as you.** The agent's own transcript may also hold the same secret, outside the engine's control.

### Layer 3: Remove a leaked secret
```text
agent-memory purge --value-from-stdin   # never pass secrets as arguments
agent-memory purge --object <id>
agent-memory purge --session <id>
```

1. **Add** the value's fingerprint to a deny list, so it is redacted on any future capture.
2. **Find** every affected object by decrypting and scanning the store. Report what was found.
3. **Rewrite:** create a redacted replacement object, then mark the original as a tombstone with `replaced_by`.
4. **Delete** the original ciphertext.
5. **Delete `derived/index.db`,** and rebuild it from surviving objects.
6. **Clean the database:** run a `wal_checkpoint(TRUNCATE)` and `VACUUM`. [SQLite's docs](https://www.sqlite.org/lang_vacuum.html) say `VACUUM` clears deleted content, and [WAL mode can retain old content until truncated](https://antonz.org/sqlite-secure-delete/).
7. **Rotate the session key:** re-encrypt surviving objects under a new key and destroy the old one. Old backups become unreadable, provided keys were never stored with them. This is [crypto-shredding](https://www.conduktor.io/glossary/crypto-shredding-for-kafka).
8. **Log** the purge: what object, when, and why, but never the value.

History stays connected, because events still point to the tombstone's ID. The event that a tool ran survives, while the secret doesn't.

### What the tool must tell the user
After a purge, the output states plainly:
- **Rotate the secret anyway.** Removal is not revocation.
- Copies may survive in the agent's transcript, shell history, OS or SSD snapshots, cloud sync, or a backup made while the key was present.

---

## 11. Test and benchmark plan

### 11.1 Engine-level tests (no LLM, run in CI)

| Test | Pass condition |
|---|---|
| Capture completeness | Replayed session: 100% of events stored or marked as a gap |
| Crash recovery | Kill between pre and post hooks: the next reconcile resolves the record |
| External edit | 100% of seeded edits detected and labelled `external` |
| Git operations | Pull, reset, rebase, checkout labelled `git_operation`; state updates |
| Delete and rename | Recorded correctly |
| Staleness | Test passes, file changes: result becomes `stale`; revert file: `verified` again |
| Bash changes | File changed by `sed` is attributed to that command |
| Superseded decision | Old decision never appears as active |
| Rebuild | Delete `derived/`: search results are equivalent after rebuild |
| Immutability | Any object changed on disk is detected |
| Fail open | Locked or corrupt store: agent continues and a gap is recorded |
| Secret canaries | No seeded detectable canary found in any file under the store, raw bytes included |
| Purge | After purge, a raw byte search of the store finds nothing; the event chain stays valid |
| Old backup | Backup without key material is unreadable after key rotation |
| Injection | Tool output with embedded instructions never reaches the brief |

### 11.2 Agent-level benchmark

**Arms.** All use the same agent, model, and scenarios:

| Arm | Setup |
|---|---|
| A | Native compaction only |
| B | Git, grep, and a human-style project notes file, with instructions to use them. **This is the strong baseline to beat.** |
| C | This engine |
| D (optional) | pi-lossless on Pi, if that agent is included. Treat as indicative, since the host agent differs |

**Scenarios** use fixture repos and run across several sessions:

| Type | Example |
|---|---|
| Recall | "Why did we choose X?" with a known answer in history |
| Stale state | The user edits a file between sessions, then asks the agent to continue |
| Superseded decision | A decision is reversed in session 2; session 3 must follow the new one |
| Git movement | `git reset` or a pull between sessions removes the agent's earlier work |
| False success | Tests passed, then code changed; agent is asked whether tests pass |
| Unknown | The answer isn't in history; the correct reply is "I don't know" |
| Continuation | A multi-session bug fix after a forced restart |
| Long history | The same questions after 32K+ tokens of unrelated work, where LCM reports its gains begin |

**Metrics:**

| Metric | Definition |
|---|---|
| Recall accuracy | Correct answers against gold answers |
| Stale-state error rate | Answers or actions relying on outdated information, per opportunity |
| False "don't know" rate | Refusal when the answer was available |
| False claim rate | Invented answer when none was available |
| Task success | Hidden tests pass at the end |
| Tokens | Total input and output, plus tokens from memory tools |
| Time | Wall clock per scenario |
| Storage growth | MB per 1,000 events and per million tokens captured |
| Overhead | Hook p50 and p95, MCP latency, peak RSS |

**Method:**
- Write gold answers and pass thresholds before running.
- Use at least 5 runs per scenario per arm, and report variance rather than one best run.
- Score mechanically where possible. For the rest, a human grades a sample without seeing which arm produced it.
- Publish the fixtures and raw results, and note that the author built the engine. LCM's benchmark is a useful warning: it came from its developers, on one benchmark split, and the advantage appeared only at larger contexts.

### 11.3 Decision thresholds

| Result | Action |
|---|---|
| C has at least 50% fewer stale-state errors than **both** A and B, with recall no worse than B and tokens within +10% of B | **Go:** build symbols, then the second adapter |
| C beats A but ties B | The value is mostly convenience. Narrow to a small capture-and-brief tool, or stop |
| C loses to B, or tokens rise substantially | Stop or rethink. Publish what was learned |

---

## 12. Comparison and what to reuse

This table reflects each project's public docs as read on 2026-11-06. "Not described" means I didn't find it, not that it is impossible.

| Project | History store | Retrieval | Real file state | Secrets |
|---|---|---|---|---|
| [LCM](https://arxiv.org/html/2605.04050v1) | Immutable store; embedded PostgreSQL in the reference | Grep, describe, expand; expansion limited to sub-agents | Left to the agent's file tools; no symbol index | Not described in what I read |
| [pi-lossless](https://pi.dev/packages/pi-lossless?page=96) | Session file is truth; SQLite is a rebuildable index | Grep, describe, bounded expand | Not described | Plaintext store; best-effort redaction |
| [hermes-lcm](https://hermesatlas.com/projects/stephenschoettler/hermes-lcm) | SQLite plus files; MIT | Many tools; advanced ones opt-in | Not described | Redaction off by default; forward-only |
| [CMV](https://arxiv.org/html/2602.22402v1) | DAG of snapshots with branch and trim | Snapshot-based reuse; 76-session single-user study | Not the focus | Not described in what I read |
| [Letta MemFS](https://docs.letta.com/concepts/memfs) | Agent memory as Markdown in git | Hot and cold files, plus memory search | Docs don't describe tracking project code | Not described in what I read |
| [Pi sessions](https://pi.dev/docs/latest/how-pi-works.md) | JSONL tree; compaction keeps originals | Tree navigation | No | Not described in what I read |
| Git | Committed content | `log`, `grep`, `blame` | Yes for files | Not for agent context |

### Reuse

| Reuse | For |
|---|---|
| Git | Committed history and blob IDs |
| SQLite, FTS5 | Storage and search |
| Gitleaks rule set | Secret detection (check its license for vendored rules) |
| MCP and agent hooks | Integration |
| tree-sitter ([Aider's repo map](https://kitemetric.com/blogs/how-aider-indexes-your-codebase-for-ai-powered-code-assistance) shows the approach) | Symbols, later |

### Borrow the idea

| Idea | From |
|---|---|
| Grep, describe, and bounded expand as tools; summaries as a cache | LCM |
| Bounded sub-reader, so big reads don't flood context | LCM, pi-lossless |
| Session source of truth with a rebuildable index | pi-lossless |
| Hot and cold context | Letta |
| Separating conversation from mechanical tool overhead | CMV |
| When a fact was true vs when it was learned | [Graphiti](https://www.emergentmind.com/papers/2501.13956) |

### Build, because I didn't find it combined elsewhere
- Change ledger tied to real file hashes.
- Reconciliation with attribution.
- Verification bound to an exact tree state.
- Computed state with `verified`, `stale`, and `unknown`.
- Purge across an otherwise immutable store.
- A public benchmark for stale-state errors.

### Don't build yet
Summarization. It's well covered, costs money, and needs a model. If long-history recall becomes the weak spot, integrating with an existing approach comes first.

---

## 13. How ADAM uses it

The engine stores and finds things. ADAM decides what to believe.

| ADAM need | Engine building block | Stage |
|---|---|---|
| Proof records | Typed links back to sources | Created in 1.4, moved in 4.1 |
| Source library and passages | Immutable objects with offsets | 4.2 |
| Thought traces | Events and links | 4.5 |
| Study sessions | Events | 5.6 |
| Tool audit | Event log | 7.2 |
| Rule and skill versions, including a hash of the locked floor | Versioned objects | 4.1 onward |
| Rebuildable search indexes | Derived store | 4.2 |

**Stays in ADAM:** logic rules, inference, the claim review gate, ontology, skill lifecycle, and fact semantics.

### The boundary
- `memory/engine_store.py` is the only ADAM file that imports `agent_memory`.
- The kernel imports nothing from the engine.
- A shared contract test suite runs against the store.
- ADAM uses the library directly. It doesn't need hooks, plugins, or an agent.

### Constraints
- It must fit the budget set in stage 0.4, with no model or network required.
- Encryption can be off for ADAM's own stores if measurements or usage justify it, but the secret-scanning rules still apply to anything captured from tools.

### Order, and why
1. **Phase 1 fixes the logic first.** Stage 1.4's proof records use a plain table for now, which is cheap because the stores are disposable until study begins.
2. **Phases 2 and 3 build and test the engine.** After 3.1, the plugin can remember the work of building ADAM itself.
3. **Phase 4 connects ADAM.** Stage 4.1 uses only the core, so it works **whichever way the 3.2 benchmark goes**.

### What the benchmark changes

| 3.2 result | Plugins | ADAM |
|---|---|---|
| Go | Build the rest and release | Uses the released package |
| No-go | Close 3.3 to 3.6 as not planned | Keeps the core as an in-repo library |

---

## 14. Risks

| Risk | Mitigation |
|---|---|
| Native agents add this themselves | Stay agent-neutral; the verified-state benchmark remains useful either way |
| Git plus a good notes file is good enough | Arm B tests this directly and can stop the project early |
| The agent ignores memory tools | The brief needs no tool call; measure tool use |
| Hooks change between agent versions | Thin adapters, version checks, transcript backstop, recorded gaps |
| Hook latency annoys users | Measure; move hot paths to a compiled helper if needed |
| Scanner misses a secret | Encryption, purge, and clear warnings; no claim of completeness |
| Memory replays a prompt injection | Brief excludes raw tool output; results are labelled as data |
| Brief grows and costs tokens | Hard cap, measured in every benchmark |
| False `verified` status | Strict definition: a pass applies only to the exact tree; anything uncertain is `unknown` |
| Scope creep from the four-store design | Symbols, graphs, and summaries wait for the go decision |

---

## 15. First shippable slice

**Name:** Truth at Session Start.

**What a user gets:** install it into Claude Code, work as usual, and every new session opens with a short, accurate account of what changed, what's verified, and what's stale. Anything from the past can be fetched by ID.

### In scope
- Claude Code hooks and an MCP server.
- Capture, secret scanning, encrypted objects.
- Change ledger and verification records.
- Reconciliation.
- Computed state and the level 0 brief.
- `mem_search`, `mem_get`, `mem_history`, `mem_state`, `mem_decisions`, `mem_decide`, and bounded `mem_expand`.
- CLI: `init`, `status`, `reconcile`, `rebuild`, `purge`, `export`.
- The engine-level tests from 11.1.

### Out of scope
Symbols, dependency graphs, summaries, semantic search, a second agent, UI, sync.

### Acceptance criteria

**Capture**
- [ ] Installs into a project with one command and can be removed cleanly, leaving the project unchanged.
- [ ] A replayed session stores 100% of events or marks each gap.
- [ ] A broken store never blocks the agent.
- [ ] Hook p95 is under 100 ms on the development machine, or the result is recorded and D2 is revisited.

**Reconciliation and state**
- [ ] An edit made outside the agent between sessions appears in the next brief as `external`.
- [ ] `git reset`, pull, and checkout appear as `git_operation`.
- [ ] A passing test turns `stale` when a file changes, and becomes `verified` again if the exact tree returns.
- [ ] A crash between hooks is resolved on the next reconcile.
- [ ] A superseded decision is never shown as active.
- [ ] If reconciliation can't run, state reads `unknown`.

**Retrieval**
- [ ] The brief stays within 500 tokens on the fixture repos and every line has a source ID.
- [ ] Each ID fetches the exact original through `mem_get`.
- [ ] The previous version of an uncommitted file can be recovered.
- [ ] Tool output containing injected instructions never reaches the brief.

**Secrets**
- [ ] Seeded detectable canaries appear nowhere in the store's raw bytes.
- [ ] Purge removes a planted secret from objects, index, and database file, and history stays connected.
- [ ] Purge output tells the user to rotate the secret.
- [ ] A store in a detected sync folder triggers a warning.

**Integrity**
- [ ] Deleting `derived/` loses no truth, and `rebuild` restores search.
- [ ] Tampering with a stored object is detected.

**Decision gate**
- [ ] The agent-level benchmark runs on this slice, its results are published in the repo, and the section 11.3 rule is applied.

---

## 16. Where it lives, and how it becomes a standalone plugin

### During development: one directory

Everything stays inside `~/ADAM`, so there is no second checkout.

```text
ADAM/
  packages/agent-memory/      # engine; own pyproject.toml; no ADAM imports
    src/agent_memory/
      store/  ledger/  reconcile/  state/  retrieve/  secrets/  cli/  mcp/
    tests/
  plugins/                    # thin per-agent adapters
    claude-code/  opencode/  pi/  codex/  gemini/  cursor/
  memory/engine_store.py      # ADAM's only link to the engine
```

CI fails if the engine imports ADAM, and the package's tests run with ADAM absent. That keeps "standalone" true from the first commit.

### How one engine serves many agents

```text
 Agent event -> thin plugin -> amem hook <agent> <event> -> shared core
 Model tool call -> amem mcp -> shared core
```

- **Core:** the `amem` CLI and MCP server, installed once per machine (`pipx` or `uv tool`, with a single-file build later if needed).
- **Plugin:** only maps that agent's events and packaging. No storage or decision logic lives in a plugin.
- **Shared memory:** all agents write to the same per-project store, so you can start in Claude Code and continue in OpenCode, and each action records which agent did it.
- **Missing core:** a plugin explains how to install it and never blocks the agent.

### Support by agent

These come from each agent's docs as read on 2026-11-06. Hook systems change, so stage 3.5 publishes a table tested against specific versions.

| Agent | Package and install | Capture | Brief at session start | Tools |
|---|---|---|---|---|
| **Claude Code** (3.1) | Plugin: `.claude-plugin/plugin.json`, `hooks/hooks.json`, `.mcp.json`; marketplace | `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop`, `PreCompact` | `SessionStart` `additionalContext` | MCP |
| **OpenCode** (3.3) | npm package in the `plugin` list of `opencode.json` | `tool.execute.before/after`, `file.edited`, message and session events | **To verify:** docs I read show injection at compaction, not session start. Fallback is a `mem_brief` tool | MCP in `opencode.json`, or the plugin `tool` helper |
| **Pi** (3.4) | Pi package through `pi install` (npm or git) | `tool_call`, `tool_result`, `session_start`, compaction events | `session_start` or the `context` event | `registerTool` or MCP |
| **Codex** (3.5) | Plugin: `.codex-plugin/plugin.json`, `hooks/hooks.json`; hooks need trust review | `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop`, `PreCompact` | `SessionStart` stdout or `additionalContext` | MCP in `config.toml` |
| **Gemini CLI** (3.5) | Extension through `gemini extensions install`. **Check status:** docs note some tiers moved to Antigravity CLI | `BeforeTool`, `AfterTool`, `BeforeAgent`, `AfterAgent`, `PreCompress` | `SessionStart` `additionalContext` | MCP |
| **Cursor** (3.5) | `.cursor/hooks.json`, or plugin hooks | `preToolUse`, `postToolUse`, `afterFileEdit`, `afterShellExecution`, `preCompact` | `sessionStart` `additional_context`, **but it is fire-and-forget, so test the timing** | MCP in `mcp.json` |
| **Windsurf, Cline, other MCP tools** (3.5) | `amem setup <agent>`, after checking official docs | None assumed | A rule file tells the agent to call `mem_brief` | MCP |
| **Aider, tools with neither** (3.5) | CLI only, after checking official docs | Files through reconciliation only | Manual | `amem` commands |

### Support tiers

| Tier | Requires | You get | You don't get |
|---|---|---|---|
| **Full** | Lifecycle hooks | Automatic capture, attribution, brief, retrieval | Nothing in the core feature set |
| **Partial** | MCP | Retrieval, state, and reconciliation of files | Automatic conversation capture; file changes read as `unattributed` |
| **Minimal** | A shell | File reconciliation and manual lookups | Conversation capture and automatic use |

### Plugin rules
- **Keep it thin.** If a new agent needs a core change, the contract was wrong, so fix the contract.
- **Shared test suite.** Replay recorded events for every adapter, so all agents meet the same behaviour.
- **Keep the context cost low.** Claude Code's docs note that an enabled plugin's tool and skill listings can use context on every turn, so expose few tools and measure the cost.
- **Treat a plugin as trusted code.** Plugins run with your permissions, so document exactly what they read and store.

### Release (stage 3.6)
1. Choose the final name and license.
2. Extract `packages/agent-memory/` and `plugins/` with `git subtree split`, keeping their history.
3. Publish the CLI, npm plugins, Pi and Gemini packages, a Claude Code marketplace, and Codex packaging.
4. Make ADAM depend on a pinned version, and remove the in-repo copy, so the ADAM repo keeps no duplicate.

### Stage map

| Stage | Delivers |
|---|---|
| 2.1 Prove the Reconciler | Throwaway test of the core idea |
| 2.2 Seal the Objects | Sections 3 and 10: objects, encryption, scanning |
| 2.3 Record the Ledger | Sections 4 and 5: events, changes, verification, decisions |
| 2.4 Reconcile the State | Sections 6 and 7 |
| 2.5 Open the Archive | Sections 8 and 9 |
| 2.6 Burn the Leak | Purge, and the tests in 11.1 |
| 3.1 First Plugin | Adapter contract and Claude Code plugin |
| 3.2 Weigh the Thesis | The benchmark in 11.2 and 11.3 |
| 3.3 to 3.5 | The other agents |
| 3.6 Release the Engine | Standalone release |
| 4.1 Connect the Engine | ADAM integration |

The "first shippable slice" in section 15 is stages 2.1 through 3.2.

---

## 17. Decisions you need to make

| # | Decision | Recommendation | Why |
|---|---|---|---|
| D1 | First agent | Claude Code, then OpenCode, then Pi | Its hook events are documented and cover what's needed, including session-start injection. OpenCode's route for that still needs verifying |
| D2 | Language | Python now; Rust or Go helper only if measured hook latency requires it | Fastest to test the thesis, and matches ADAM. Risk: process startup time |
| D3 | Store location | User data directory, per project | Avoids commits and sync. Cost: it doesn't travel with the repo unless exported |
| D4 | Key storage | OS keychain, falling back to a passphrase-derived key | WSL often lacks a keychain. A plain key file is simpler but gives weaker protection |
| D5 | Default capture | Store tool output and uncommitted edits up to 10 MB each; hash only for binary and excluded paths | Your call on privacy vs completeness |
| D6 | Benchmark budget | Agent-level runs on one model first | Runs cost real API money: scenarios x arms x at least 5 repeats |
| D7 | Open source | Public from the first release, MIT, with benchmark data public | A published benchmark is more credible. Check licenses before reusing other projects' code |
| D8 | Name | Choose before stage 3.6 | `amem` and `agent-memory` are working names. The repo question is settled: it stays in ADAM until 3.6 |

---

## 18. Sources

- LCM paper: <https://arxiv.org/html/2605.04050v1>
- pi-lossless: <https://pi.dev/packages/pi-lossless?page=96>
- hermes-lcm: <https://hermesatlas.com/projects/stephenschoettler/hermes-lcm>
- CMV paper: <https://arxiv.org/html/2602.22402v1>
- Letta MemFS: <https://docs.letta.com/concepts/memfs>
- Pi internals: <https://pi.dev/docs/latest/how-pi-works.md>
- Pi extensions: <https://pi.dev/docs/latest/extensions>
- Claude Code plugins: <https://code.claude.com/docs/en/plugins>
- OpenCode plugins: <https://opencode.ai/docs/plugins/>
- OpenCode MCP: <https://opencode.ai/docs/mcp-servers/>
- Codex hooks: <https://learn.chatgpt.com/docs/hooks>
- Gemini CLI hooks: <https://geminicli.com/docs/hooks/reference/>
- Gemini CLI extensions: <https://geminicli.com/docs/extensions/>
- Cursor hooks: <https://cursor.com/docs/agent/hooks>
- Claude Code hooks: <https://code.claude.com/docs/en/hooks>
- Graphiti and Zep paper summary: <https://www.emergentmind.com/papers/2501.13956>
- SQLite VACUUM: <https://www.sqlite.org/lang_vacuum.html>
- SQLite secure delete and WAL (secondary): <https://antonz.org/sqlite-secure-delete/>
- Crypto-shredding (vendor overview): <https://www.conduktor.io/glossary/crypto-shredding-for-kafka>
- Aider repo map (secondary): <https://kitemetric.com/blogs/how-aider-indexes-your-codebase-for-ai-powered-code-assistance>
