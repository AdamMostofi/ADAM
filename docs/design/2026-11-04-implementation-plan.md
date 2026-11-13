# ADAM — Architecture and UI/UX Implementation Plan

**Status:** Superseded by [ROADMAP.md](../ROADMAP.md) (the order of work) and [DECISIONS.md](../DECISIONS.md). Kept as a record of the reasoning. Its LanceDB and fastembed details predate Stage 0.5.  
**Date:** 2026-11-04  
**Repository:** ADAM  
**Scope:** durable record of the neuro-symbolic architecture direction, the
Hallmark evaluation, and the bounded UI/UX audit and polish plan for the Flask
interface.

---

## 1. Purpose

This document records the decisions that came out of the architecture and
interface review, so the next implementation session does not have to
reconstruct them from conversation history.

It has two jobs:

1. Preserve the neuro-symbolic architecture recommendation and its execution
   phases.
2. Record the UI/UX audit of the existing `interface/web` surface, including the
   design read, dials, verified findings, fix order, and acceptance checks.

This is a plan, not a claim that the architectural changes already exist. The
only work approved for the current pass is the interface audit and the bounded
UI fixes listed in §6.

The existing design record for the neuro-symbolic direction is
[`neuro-symbolic-vision.md`](./neuro-symbolic-vision.md). This document links to
it rather than rewriting it.

---

## 2. What the Current System Is

The current system is a local-first reasoning shell built from:

- A forward-chaining subject–predicate–object engine.
- SQLite for facts and state.
- LanceDB for vector rows.
- NetworkX for the knowledge graph.
- A small local model used as the "Mouth", not as a reader.
- A Flask interface at `interface/web`.

The interface is the only web surface in this repository. There is no separate
marketing site. "Site and interface" in the request therefore means the Flask
app served by:

```bash
python -m interface.web.app
```

at `http://localhost:7860`.

---

## 3. Architecture Direction

### 3.1 Problems to fix

- **Memory is one undifferentiated store.** Source facts, inferred facts, and
  vector rows are mixed together. Inferred data can taint the source store.
- **The source library is missing.** There is no immutable place for books,
  passages, page offsets, and hashes, so re-reading and cross-book synthesis
  cannot be done safely.
- **The current model is a voice, not a reader.** The Mouth has a very small
  context limit and cannot ingest a book.
- **The test surface is not isolated.** The Flask app creates a global
  `ADAMCore` at import time, so integration tests can write into the same
  stores as the running application.
- **Existing data is polluted.** Duplicate facts and vector rows with duplicate
  IDs mean the current store cannot be trusted as a benchmark.
- **There is no tool registry.** File, web, and terminal access are described
  in the design but not implemented.
- **Skills are too narrow.** Current skills are at most two-premise inference
  rules, not procedures with preconditions, steps, tools, and success tests.

### 3.2 Target memory model

Use five memory types rather than one "memory":

| Memory | Contents |
|---|---|
| **Source library** | Immutable books, pages, passages, offsets, hashes. |
| **Working memory** | Current goal, retrieved passages, active hypotheses, plan. |
| **Semantic memory** | Concepts, claims, ontology, confidence, provenance. |
| **Episodic memory** | Study sessions, questions, failures, tool calls, outcomes. |
| **Procedural memory** | Skills, strategies, tool-use procedures. |

Only reviewed claims become semantic facts. Candidate claims live in a review
queue. That firewall is what prevents book hallucination from becoming
"knowledge".

### 3.3 Thought trace, not fake reasoning prose

Do not make the system think in raw binary. Binary is a substrate, not a
language of thought. Use a typed thought DAG instead:

- `PERCEIVE`, `RECALL`, `LINK`, `ANALOGIZE`, `INFER`, `HYPOTHESIZE`, `TEST`,
  `PLAN`, `ACT`, `REFLECT`, `CONSOLIDATE`.

Each node stores inputs, outputs, confidence, provenance, and timestamp. A
renderer translates the trace to English on demand. The trace is the truth; the
English is a projection. This gives inspectability without generating a wall of
fake chain-of-thought prose.

### 3.4 Book study loop

1. Survey the structure.
2. Chunk by structure first, then by ordered token windows with offsets.
3. Extract entities, definitions, claims, questions, and procedures.
4. Link to known concepts and flag unknowns or contradictions.
5. Self-test and mark gaps.
6. Consolidate: approve, reject, merge, or defer.
7. Revisit passages when new knowledge creates a gap.
8. Synthesize new concept, analogy, or hypothesis nodes across books.

"Read it all at once" is not the goal. Multiple passes with provenance is.

### 3.5 Ontology

Separate two layers:

- **Fixed meta-ontology:** Entity, Concept, Relation, Claim, Process, Question,
  Goal, Evidence, Tool, Skill.
- **Learned domain ontology:** concepts, aliases, predicate definitions,
  hierarchy, inverse relations.

The first book should teach *how to learn*, not *what to believe*. GEB is a
useful seed for isomorphism, recursion, self-reference, levels, and strange
loops, but it should not become an absolute constitution. A short logic and
relations primer before GEB is a better curriculum.

### 3.6 Layers and procedures

Keep the existing layer model and extend it:

- **L0:** immutable inference rules.
- **L1:** learned concepts and claims.
- **L2:** learned inference rules.
- **L3:** procedures and strategies.
- **L4:** meta-cognition — when to reread, ask, test, or use a tool.

Every learned item needs provenance, confidence, fitness, and a lifecycle:
candidate → tested → active → deprecated. Nothing learned can rewrite L0.

Only generalize a procedure after three real traces share the same shape
(Rule of Three).

### 3.7 Storage and runtime decisions

- **SQLite is the source of truth.** Keep the relational store for facts,
  claims, provenance, episodes, and review state.
- **Treat LanceDB as an optional index, not a second truth.** If vector search
  is needed, it must be rebuildable from SQLite.
- **Benchmark before changing the embedding default.** Compare Needle with the
  current fastembed path on the real corpus. Remove fastembed from the default
  path only if the benchmark supports it.
- **Do not add a hosted JEV decision API.** Use a local decision layer that can
  be inspected and tested.
- **Use an app factory and dependency injection for tests.** The current global
  `ADAMCore` at import time is the root cause of test pollution.
- **Add audit, backup, and clear commands** before any migration.
- **Keep the 400 MB peak-RSS target.** *(Superseded 2026-11-09: the current definition is in [memory-budget.md](./memory-budget.md).)* The documented current state is roughly
  397 MB for the core plus 62 MB for `llama-server`; that is already at the
  ceiling, so new components need measured headroom.
- **Book learning writes to memory through review.** Do not let ingestion write
  directly into the semantic store.
- **Defer the procedure engine.** It depends on the source library, review
  queue, and tool registry; building it first would be speculative.

### 3.8 Execution phases

**Phase 0 — Stabilize**
- Back up the current store.
- Audit duplicate facts and vector IDs.
- Isolate test stores.
- Record baseline RSS and latency.

**Phase 1 — Source and semantic store**
- Add SQLite schema for sources, passages, claims, provenance, and review state.
- Migrate existing facts with source labels.
- Add audit/backup/clear tooling.

**Phase 2 — Retrieval**
- Benchmark Needle against the current embedding path.
- Make vector rows rebuildable from SQLite.
- Remove duplicate IDs and verify retrieval quality.

**Phase 3 — Learning loop**
- Add book ingestion and structural chunking.
- Add candidate claims and review queue.
- Add provenance rendering and re-read triggers.

**Phase 4 — Decision layer and tools**
- Add the local decision layer.
- Add a minimal tool registry with file, web, and terminal tools.
- Add procedures only after three real traces prove the shape.

### 3.9 Weak points

- A small local model will produce noisy extraction; review is mandatory.
- CPU-only ingestion will be slow for full books.
- The 400 MB ceiling limits model size and embedding options.
- Ontology drift is a real risk if the learned layer is not reviewed.
- The current test suite cannot be trusted until global state is removed.
- Tool access expands the security surface; sandboxing is not optional.

---

## 4. Hallmark Evaluation

### 4.1 What Hallmark is

Hallmark is a design skill/framework for producing landing pages and marketing
surfaces. The reviewed version is MIT-licensed, v2.0.0. Its public surface
includes:

- 50 themes.
- 755 openly licensed Wikimedia photos.
- A static, zero-dependency linter.
- A render tier that needs Chrome and `puppeteer-core`.
- Support for OpenCode.
- A Floor / Reflex / Finish workflow.
- Fresh-context reviews.
- It does not automatically redesign an existing project unless explicitly
  asked.

### 4.2 Where it fits

**Adopt Hallmark as the primary skill for new landing pages and marketing
surfaces.**

Do not use it as the primary skill for the ADAM app UI. ADAM is a dense,
stateful workstation, not a marketing page. The app needs design-system
continuity, focus behavior, data states, and responsive console behavior; those
are better served by the existing `design-master` workflow and the current
token system.

### 4.3 Skill disposition

- **Keep `design-taste-frontend`** for app and dashboard UI.
- **Keep `ui-ux-pro-max`** as a reference database, not as the primary design
  authority.
- **Retire `gpt-taste`, `high-end-visual-design`, and `premium-frontend-ui`**
  from the default Hallmark path. They overlap and create conflicting
  instructions.
- **`design-taste-frontend-v1` is redundant** with the current variant.
- **`impeccable` installed here is a TypeUI brand system**, not
  `pbakaus/impeccable`. Do not treat them as the same skill.
- **`redesign-existing-projects`** is the right fallback for app UI and
  non-Hallmark redesigns.

### 4.4 Integration rules

- Do not co-load Hallmark with the retired overlapping design skills.
- Use Hallmark for landing pages, not for the ADAM console.
- Use `design-master` for the current ADAM UI audit.
- Treat visual output as evidence, not as a claim. Capture screenshots and
  inspect the real surface.

---

## 5. UI/UX Audit

### 5.1 Design read

**DESIGN READ:** Reading this as a dense, local-first reasoning workstation
(app UI, not a marketing site) for a single technical operator, with a machined
Imperial command-surface language, leaning toward the existing industrial/cyber
profile and native CSS.

**DIALS:** `DESIGN_VARIANCE=5` `MOTION_INTENSITY=4` `VISUAL_DENSITY=7`

**PROFILE:** industrial / cyber (existing brand language)

**STACK:** Flask + vanilla HTML/CSS/JS; no framework, no build step, no new
dependencies.

**MODE:** preserve. The brand, terminology, routes, API contracts, and shell
structure stay. This is execution polish and accessibility repair, not a
redesign.

**CONSTRAINTS:** preserve copy and section names; keep the 232 px rail, 76 px
topbar, graphite/brass/lime token system; no horizontal overflow at 320–1440;
44 px touch targets where applicable; honor reduced motion; no memory-backend
work.

### 5.2 Dial rationale

| Dial | Value | Rationale |
|---|---:|---|
| `DESIGN_VARIANCE` | 5 | Match the existing structured shell. It is asymmetric and cockpit-like, not chaotic or symmetric marketing. |
| `MOTION_INTENSITY` | 4 | Existing motion is functional and mechanical: 120/220/420 ms transitions, panel entry, status breathe. No new choreography. |
| `VISUAL_DENSITY` | 7 | The console is intentionally dense. Airy-fying it would break the product identity. |

### 5.3 Verified findings

These were checked against the live app and the current CSS/JS, not inferred
from screenshots.

| ID | Finding | Root cause |
|---|---|---|
| F1 | Cognition graph node labels are unreadable; edge labels are low quality. | `interface/web/static/js/app.js` sets node label color to `--surface-0` (near-black) on a near-black canvas. Edge labels use a low-contrast 10 px style. |
| F2 | At 390 px, there is a 12 px dead gap above `main`. | `.workspace` grid row is `var(--topbar-h)` = 76 px, while the mobile `.topbar` is forced to 64 px. |
| F3 | Mobile bottom-nav labels are 8.64 px. | `.rail-label` mobile rule uses `0.54rem`. |
| F4 | The high-contrast toggle is inaccessible on mobile. | `.rail-foot`, which contains `#contrast-toggle`, is `display:none` at ≤720 px. |
| F5 | New / Export / Refresh disappear below 560 px. | `.topbar-actions .ghost-btn { display:none; }` hides the ghost actions. |
| F6 | Rites renders the raw value `false` for mood shift. | `app.js` passes the boolean through `String(value)`. |
| F7 | The skip link may not move focus reliably. | `<main id="main">` has no `tabindex`, and the `hashchange` handler treats `#main` as an unknown route and focuses `#section-vox`. |

Measured contrast is otherwise acceptable:

- `--text` on `--surface-0`: 15.58:1
- `--text-dim` on `--surface-0`: 9.39:1
- `--text-mute` on `--surface-0`: 5.42:1
- `--text-mute` on `--surface-2`: 4.91:1
- Gold on `--surface-0`: 8.87:1

### 5.4 Fix plan

**F1 — Graph legibility**
- Use `--text` for node labels and `--text-dim` for edge labels.
- Add a surface-colored text stroke so labels remain legible over edges.
- Keep the existing node and edge palette; this is a legibility fix, not a
  graph redesign.
- Rebuild the graph when contrast changes.

**F2 — Mobile shell**
- Make the mobile grid row and topbar height agree at 64 px.
- Remove the dead gap above `main`.

**F3 — Mobile nav**
- Raise `.rail-label` to 10–11 px with tighter letter spacing.
- Verify at 320, 375, and 390 px; no clipped `Data-Vaults` label.

**F4 — Mobile high contrast**
- Keep the desktop rail toggle.
- Add a compact topbar `HC` toggle visible only on narrow screens.
- Both toggles share `data-contrast-toggle`; `aria-pressed` and titles stay in
  sync.

**F5 — Mobile actions**
- Stop hiding every ghost action below 560 px.
- Keep the action set available at 390 px; allow the title to ellipsize instead
  of removing controls.
- If 320 px proves too tight, keep the primary action and hide only the
  secondary action at the smallest breakpoint.

**F6 — Rites**
- Render mood shift as `Detected` or `None`.
- Do not change the API payload.

**F7 — Skip link**
- Add `tabindex="-1"` to `main`.
- Ignore non-section hashes in the `hashchange` handler so `#main` does not
  redirect focus to Vox.

### 5.5 Verification

Use Playwright against the live Flask app with temporary `ADAM_DB` and
`ADAM_LANCE` paths.

Viewports:

- 320 × 568
- 375 × 812
- 390 × 844
- 768 × 1024
- 1024 × 768
- 1440 × 900

Checks:

- No horizontal overflow.
- Topbar and main meet without a gap.
- Bottom-nav labels fit and are legible.
- Every section has at least one visible topbar action at 390 px.
- High-contrast toggle is reachable and switches both standard and high modes.
- Skip link moves focus to `main`.
- Graph node labels are readable at 1440 and 390.
- Rites displays `None` or `Detected`, never `false`.
- Focus-visible rings remain visible.
- Reduced motion does not animate status or reveal transitions.
- Legacy route/API tests still pass.

Evidence:

- Before/after screenshots for Vox, Cognition, Data-Vaults, Skills, and Rites.
- Computed-style output for the topbar gap, nav font size, and overflow.
- Focus trace and contrast toggle state.
- Test run output.

### 5.6 Deferred

- Chat body font-size normalization beyond the audited surfaces.
- A full design-token audit for every micro-label.
- Graph interaction redesign.
- New topbar overflow menu.
- Any memory-backend, ontology, or tool-registry implementation.
- Landing-page work with Hallmark.

---

## 6. Execution Order

1. Save this plan in the repository.
2. Fix F2, F3, F4, F5, and F7 in the shell.
3. Fix F1 and F6.
4. Run Playwright QA at the viewports above.
5. Run focused interface tests with temporary stores.
6. Commit docs separately from UI changes.
7. Record actual evidence in the final response; update this document only if a
   result changes the plan.

### Commit shape

Follow the repository's existing style:

```text
docs: add architecture and UI/UX implementation plan
ui: fix mobile shell, focus, and contrast access
ui(cognition): make graph labels legible
ui(rites): render mood shift as a state
```

---

## 7. Acceptance Criteria

- The plan document exists in `docs/design/` and includes the architecture,
  Hallmark, design read, dials, findings, fix plan, verification, and deferred
  scope.
- The seven UI findings are fixed or explicitly deferred with a reason.
- No API route, payload, copy, terminology, or brand change is introduced.
- No new dependency or framework is added.
- Playwright evidence exists for desktop and mobile, standard and high contrast.
- The focused interface tests pass against a temporary store.
- The final response names the evidence and any remaining risk.
