# ADAM — Project Status and Next Steps

**Status:** Current — implemented state and recommended next work
**Date:** 2026-11-06
**Repository:** ADAM
**Scope:** State of ADAM at `a4a21b5`: what it is, what is shipped, what is
missing, why the architecture is shaped this way, and where work should start.

---

## 1. Purpose and Status

This document is a durable record of the project state. It exists so the next
implementation session does not have to reconstruct the architecture, the
shipped surface, the known gaps, and the recommended order from memory.

The boundary is explicit: this is an assessment and a plan. No code, test,
configuration, or interface change accompanies it.

Observations are taken at commit `a4a21b5` on `master`. The repository is clean
and `master` equals `origin/master` at that commit.

Claims about shipped features are checked against the repository tree, the
README, the changelog, the design records, and the current code. Measurements
not re-run for this document are marked as inherited.

---

## 2. What ADAM Is

ADAM is a local-first neuro-symbolic machine intelligence. It combines a small
symbolic reasoning kernel with persistent memory, a learning loop, an affect
layer, an input parser, a speech layer, and a console for inspection.

The repository is organized around five surfaces:

- `kernel/` — facts, rules, forward chaining, backward proof, unification,
  contradiction handling, and truth revision.
- `memory/` — exact storage, semantic storage, a relationship graph, attention
  ranking, and persistence.
- `learning/` — pattern extraction, skill compilation, fitness tracking, error
  correction, and cross-domain mapping.
- `interface/` — the CLI, the Ear, the Mouth, and the Flask web console.
- `tests/` — unit, integration, stress, fuzz, and property tests.

The operating premise is local inference. The runtime path does not require a
hosted model or a cloud service. The language model is a voice, not the mind.

The scope is intentionally small. ADAM is a working symbolic reasoning shell
with persistent memory, not a general reasoner and not a book-learning system
yet. That distinction matters for every decision that follows.

---

## 3. What Has Been Built

The release history is concrete:

| Version | Delivered |
|---|---|
| V0.2 | Symbolic kernel |
| V0.3 | Memory system |
| V0.4 | Learning system |
| V0.5 | EQ layer |
| V0.6 | CLI and Flask interface |
| V0.7 | Ear and Mouth |
| V0.8 | Interface overhaul and Hyperon-derived reasoning |

### Kernel

The kernel implements 16 foundational rules, a predicate-indexed agenda for
forward chaining, goal-directed backward proof, `?variable` pattern queries via
`query_pattern`, contradiction detection, and staged truth revision.

The inference engine indexes facts by predicate and processes an agenda instead
of scanning every fact against every rule. The backward prover searches from a
goal without mutating beliefs. The truth layer separates strength from
confidence and folds independent derivations through a revision operator.

### Memory

The memory system uses SQLite for exact facts and proof chains, LanceDB for
semantic recall, NetworkX for relationships, and an ECAN-style attention bank
for ranking.

Every stored fact is written to the exact store, the graph, and the semantic
index. Recall starts with exact text search, falls back to semantic search, and
re-ranks results by attention. The graph supplies related context for the
data-vault views.

### Learning

The learning layer contains a pattern extractor, a skill compiler, fitness
tracking, error correction, and cross-domain analogy mapping.

Compiled skills can be exported and imported as JSON bundles. A skill can be
converted into a Layer 2 inference rule when it has at most two premises. The
fitness score combines compiled confidence with observed success.

### EQ

The EQ layer performs primary and secondary appraisal, produces an emotional
tone and goal status, and derives response parameters such as warmth, depth,
directness, and caution. A rolling baseline records interaction state and
supports mood-shift detection.

### Ear and Mouth

The Ear wraps Needle 2 and extracts action, topic, sentiment, and urgency. The
Mouth wraps TinyChat15M through `llama-server` and renders the response.

The Mouth has a 60-character context window in the current prompt builder. It
is a speech layer. It is not used to read, extract, or reason.

### Interface

The V0.8 interface is a Flask application with vanilla HTML, CSS, and
JavaScript. It has no Node runtime and no build step.

The console contains Vox, Cognition, Data-Vaults, Skills, and Rites sections. It
includes a left rail, hash routing, chat persistence, a `full` and `simple` mode
selector, a markdown sanitizer, a graph view, telemetry, a mobile dock, and a
warm light/dark theme.

Recent interface work is recorded in commits `6fb6a2d` and `a4a21b5`.
`6fb6a2d` restored mobile hierarchy and keyboard access. `a4a21b5` replaced the
high-contrast mode with a warm light/dark theme, updated the graph tokens, and
fixed the 320 px topbar overflow.

### Working end to end

The working paths are CLI chat, `POST /api/chat`, fact recall with an EQ-adjusted
answer, live graph/stats/skills/facts endpoints, and theme persistence. The
missing paths are durable learning from chat, document ingestion with citation
and review, and tool discovery, approval, invocation, and audit.

---

## 4. Current Reality: Gaps and Their Consequences

The code is ahead of the original vision in some places and behind it in
others. The gaps below change the next implementation order.

| Gap | Evidence | Consequence |
|---|---|---|
| Chat does not learn | `interface/core.py:27` | No durable skill from a turn |
| Premises never extracted | `learning/pattern_extractor.py:49` | No usable rule |
| Global core at import | `interface/web/app.py:11` | Tests share production state |
| Store is polluted | 16 duplicate facts; zero skills | No trustworthy baseline |
| Substrate is missing | No library, DAG, queue, registry | No citation or trace |
| Memory is at the ceiling | ~397 MB core plus ~62 MB server | Little headroom |

### Chat does not learn

`ADAMCore.chat()` parses intent, appraises the message, recalls facts, adds
recalled facts to the engine, runs inference, stores inferred facts, recalls
again, and renders a response.

The path never calls `LearningEngine.learn_from_proof()` and never calls
`compile_skill()`. The learning system exists at library level. It is not wired
into the live conversation loop.

The consequence is that conversation produces answers but not durable learning.
A fact can be stored, and an inference can be stored, but the proof trace is not
converted into a reusable skill during the turn.

### Premises are never extracted

`PatternExtractor` in `learning/pattern_extractor.py` initializes
`premises = []` and never appends to it. The parser extracts a conclusion from
the right side of a proof step, but it does not retain the left side or the rule
that produced it.

The consequence is structural: a pattern has a conclusion but no premise body.
Skill compilation from chat traces cannot produce a usable rule until premise
extraction is real.

### The Flask app builds global state at import

`interface/web/app.py` creates `app` and `core` at module import time. The core
reads `ADAM_DB` and `ADAM_LANCE`, defaulting to the production paths. The Flask
tests import that module, so tests operate on the same store as the application
unless the environment is set before import.

The consequence is that production data is at risk from a test run, and a
learning benchmark cannot distinguish code behavior from residual data.

The store contains 16 duplicate facts and no compiled skills. The substrate
lacks a source library, a typed thought DAG, a review queue, and a tool
registry. The inherited memory measurement leaves little headroom. Those three
conditions are what Phase 0 and Phase 1 exist to change.

### The common thread

The reasoning substrate is real. The ingestion-and-learning path around it is
not connected. The next work is therefore not a larger model or another screen.
It is the missing substrate that makes learning trustworthy.

---

## 5. Architecture Decisions and Rationale

The decisions below are recorded in `./neuro-symbolic-vision.md` and
`./2026-11-04-implementation-plan.md`. They are repeated with the reason and
the tradeoff, because the reason keeps the next implementation from drifting.

| Decision | Why | Tradeoff |
|---|---|---|
| Local-first, 400 MB cap | Privacy and offline use | At the ceiling |
| Mouth only | Small model cannot read | Separate Reader needed |
| Immutable L0 | Auditability; no drift | Learned layer constrained |
| Five memory types | Provenance; no taint | More schema and review |
| SQLite truth; Lance index | Integrity; rebuildable | Reindex cost |
| Typed thought DAG | Inspectable; no fake prose | Renderer and viewer |
| Review-gated study | Noisy extraction must not persist | Slower ingestion |
| Fixed meta-ontology | First book teaches method | Ontology governance |
| Approval-gated tools | Grounding with bounded risk | Approval UX and sandbox |
| Rule of Three | Avoid speculative abstraction | Slower growth |
| JEV optional | Discriminative, not a Reader | Network and privacy |
| Flask and vanilla JS | Zero build; offline; low RAM | Manual component work |

Three decisions are constraints rather than preferences. The 400 MB cap
determines which models and runtimes are possible. The Mouth-only role prevents
the voice model from being mistaken for a reader. The immutable L0 floor
prevents learned content from rewriting the trust base.

The other decisions are reversible, but reversing them has a cost. Five memory
types can collapse into fewer tables later, but provenance lost at write time is
hard to reconstruct. A thought DAG can be simplified, but a trace not recorded
cannot be inspected. Tools can be added later, but a tool call not audited
cannot be reviewed.

### The invariant

> Truth lives in a durable, inspectable store. Everything derived is
> rebuildable. Nothing enters without a path back to its source.

That invariant is the reason for SQLite as the source of truth, LanceDB as an
index, review-gated claims, and a typed trace. It is also the test for future
work: if a feature cannot name where its data lives, how it is rebuilt, and how
it points back to a source, it is not ready.

---

## 6. Roadmap

The phases below come from `./neuro-symbolic-vision.md` section 2.4. They are a
dependency order, not a calendar.

| Phase | Goal | Exit criterion |
|---|---|---|
| 0 — Stabilize | Isolate tests and audit data | Production data unchanged |
| 1 — Substrate | Library, trace, working memory | Citation and trace |
| 2 — Book study | Ingest, chunk, review claims | Chapter with citations |
| 3 — Ontology | Aliases, hierarchy, analogy | Justified cross-source link |
| 4 — Tools | Registry, sandbox, audit | Read plus approved write |
| 5 — Interface | Library, review, trace, approvals | Study loop in the UI |

Phase 0 is a prerequisite for every later phase. Phase 1 must deliver a
citation and a structured trace before book ingestion is meaningful. Phase 2
must pass the reread test before ontology work has a corpus to generalize over.
Phase 3 must produce a justified cross-source link before transfer claims are
credible. Phase 4 must audit every tool call before write tools are enabled.
Phase 5 exposes the loop in the console after the underlying paths work.

---

## 7. Recommended Starting Point

The recommended order is Phase 0 first, then one thin Phase 1 vertical slice.
The slice is deliberately smaller than the full phase.

### Phase 0, in order

1. Add a Flask app factory and inject `ADAMCore`.
2. Make every test construct its own temporary SQLite and LanceDB paths.
3. Add a test that hashes production stores before and after the test run.
4. Back up `adam_memory.db`, `adam_vectors.lance`, and `adam_save/`.
5. Audit and deduplicate facts and vector IDs.
6. Normalize the embedding model used by `MemorySystem` and `SemanticIndex`.
7. Record baseline RSS for the core and `llama-server`.

The acceptance check for step 3 is concrete: the hashes before and after the
Flask test run must be identical. The acceptance check for step 7 is a recorded
number, not an impression.

### Why stabilization comes first

Every later phase writes to the same stores. Book ingestion will write passages
and claims. Review will promote claims into semantic memory. Tools will write
files and audit records. If isolation and backup do not exist first, an
ingestion bug becomes a data-loss incident, and a learning result becomes a
measurement of residue.

The 400 MB ceiling makes this urgent rather than theoretical. A new component
must be measured against the baseline before it becomes resident.

### The first vertical slice

Ingest one Markdown or plain-text file. Store its passages with source name,
offset, and hash. Retrieve a passage for a question with an exact citation.
Show the citation in the console next to the answer.

The slice has five acceptance criteria:

1. One file is ingested exactly once.
2. Passages persist with source name, offset, and hash.
3. A query returns the matching passage with a citation.
4. The UI displays the citation next to the answer.
5. A second ingest does not duplicate passages.

The slice excludes EPUB, PDF, claim extraction, review queues, ontology work,
and tools. Those are later phases. The slice proves the path that every later
phase depends on: source to passage to citation to user-visible answer.

### What the slice proves

The slice proves that ADAM can preserve provenance through storage and
retrieval. It does not prove understanding. It proves the precondition for
understanding: a claim can be traced back to an exact passage.

That is the correct first milestone because it is testable, visible, and
independent of model quality. A small model can still produce a citation if the
retrieval path is correct.

---

## 8. Evidence and Verification Notes

### Baseline

The baseline is `master` at `a4a21b5`. Supporting interface commits are
`6fb6a2d` and `a4a21b5`. The repository is clean and synchronized with
`origin/master` at the baseline.

### Sources used

- `README.md` for the architecture summary, V0.8 surface, and release roadmap.
- `CHANGELOG.md` for the V0.2 through V0.4 delivered features.
- `docs/COMMITS.md` for the memory measurements and historical decisions.
- `./neuro-symbolic-vision.md` for the memory types, thought DAG, book study
  loop, ontology decision, and Phase 0 through Phase 5.
- `./2026-11-04-implementation-plan.md` for the storage, runtime, and UI plan.
- The repository tree and current code for the gap evidence.

### Verified in place

The following were checked directly:

- Component paths under `kernel/`, `memory/`, `learning/`, and `interface/`.
- The version claims in the README and changelog.
- The commit hashes `a4a21b5`, `6fb6a2d`, and `1d2a5f5`.
- The Phase 0 through Phase 5 definitions and exit criteria.
- The links to the two related design records.
- The current SQLite count: 16 facts, all duplicates of `bird can fly`.
- The absence of a root-level `skills/` directory and compiled skills.
- The chat path in `interface/core.py` and the global core in
  `interface/web/app.py`.
- The missing premise population in `learning/pattern_extractor.py`.

### Inherited rather than re-measured

The following figures are inherited from `docs/COMMITS.md` and were not
re-measured for this document:

- Approximately 397 MB resident memory for the core.
- Approximately 62 MB resident memory for `llama-server`.
- The 400 MB target itself.

### Follow-up candidate

`README.md` does not link the two most recent design records. A future docs-only
change could add those links. That change is recorded here and is not part of
this document.

### Related records

- `./neuro-symbolic-vision.md` — direction, decisions, and phases.
- `./2026-11-04-implementation-plan.md` — architecture, storage, and UI plan.
- `../COMMITS.md` — historical measurements and technical decisions.
