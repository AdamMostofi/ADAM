# ADAM Roadmap

**Status:** Current: 10 phases, 53 stages. This is the single order of work. Every stage has one previous and one next stage, and only one stage runs at a time. It replaces the phase numbers in older design docs, which remain useful as records of the reasoning.

Memory engine design: [2026-11-06-agent-memory-engine.md](design/2026-11-06-agent-memory-engine.md).

**Rules:** phases only group stages and hold no work of their own. Each piece of work belongs to exactly one stage. On a no-go at stage 3.2, close 3.3 to 3.6 as not planned and continue at 4.1.

## Phase 0 — Stabilize the Vault ([#15](https://github.com/AdamMostofi/ADAM/issues/15))

Make the data and tests safe before any other change.

| Stage | Issue | Name | What it does |
|---|---|---|---|
| 0.1 | [#21](https://github.com/AdamMostofi/ADAM/issues/21) | Secure the Vault | Back up the current stores and record exactly what is in them. |
| 0.2 | [#22](https://github.com/AdamMostofi/ADAM/issues/22) | Seal the Wards | Stop tests and imports from touching real data. |
| 0.3 | [#43](https://github.com/AdamMostofi/ADAM/issues/43) | Guard the Gates | Add automatic test runs, pinned dependencies, and remove machine-specific paths. |
| 0.4 | [#33](https://github.com/AdamMostofi/ADAM/issues/33) | Set the Budget | Decide what the limit means and measure every component against it. |
| 0.5 | [#32](https://github.com/AdamMostofi/ADAM/issues/32) | Choose the Index | Stop vector-store bloat and choose the index and embedding model from measurements. |
| 0.6 | [#23](https://github.com/AdamMostofi/ADAM/issues/23) | Purge and Reforge | Reset to a clean store where one fact is one row and one vector. |

## Phase 1 — Repair the Floor ([#26](https://github.com/AdamMostofi/ADAM/issues/26))

Make the logic correct before it is treated as immutable.

| Stage | Issue | Name | What it does |
|---|---|---|---|
| 1.1 | [#27](https://github.com/AdamMostofi/ADAM/issues/27) | Mend the Rites | Fix rules that derive false conclusions or never fire, and the tests that protect them. |
| 1.2 | [#28](https://github.com/AdamMostofi/ADAM/issues/28) | Order the Agenda | Get the same beliefs regardless of fact order, and remove the slowdown. |
| 1.3 | [#29](https://github.com/AdamMostofi/ADAM/issues/29) | Name the Bonds | Stop `is` from producing conclusions like `rex is species`. |
| 1.4 | [#30](https://github.com/AdamMostofi/ADAM/issues/30) | Keep the Chain | Record every premise, rule, and confidence behind a derived fact. |
| 1.5 | [#31](https://github.com/AdamMostofi/ADAM/issues/31) | Hold the Contradiction | Make contradictions real state, and let specific evidence override general defaults. |
| 1.6 | [#36](https://github.com/AdamMostofi/ADAM/issues/36) | Wake with Memory | Make a restarted ADAM know what it knew before. |
| 1.7 | [#37](https://github.com/AdamMostofi/ADAM/issues/37) | Steady the Appraisal | Stop `know` counting as negative and each turn being recorded twice. |
| 1.8 | [#44](https://github.com/AdamMostofi/ADAM/issues/44) | Tell the Truth | Correct the README and design docs to match what actually runs. |

## Phase 2 — Forge the Memory Engine ([#47](https://github.com/AdamMostofi/ADAM/issues/47))

Build the core of the Lossless Tree Memory Engine, with no dependency on ADAM.

| Stage | Issue | Name | What it does |
|---|---|---|---|
| 2.1 | [#50](https://github.com/AdamMostofi/ADAM/issues/50) | Prove the Reconciler | Test the two riskiest ideas cheaply: attributing file changes, and rebuilding state by replaying a log from a checkpoint. |
| 2.2 | [#51](https://github.com/AdamMostofi/ADAM/issues/51) | Seal the Archive | Create `packages/agent-memory/` with the canonical event format, the append-only log, and a full raw archive. |
| 2.3 | [#52](https://github.com/AdamMostofi/ADAM/issues/52) | Grow the Tree | Make the historical tree, the typed relationship graph, development paths, and planning records part of the core. |
| 2.4 | [#53](https://github.com/AdamMostofi/ADAM/issues/53) | Map the Code | Track every file version, keep an incrementally updated code dependency graph, and record verifications with full context. |
| 2.5 | [#54](https://github.com/AdamMostofi/ADAM/issues/54) | Survive the Crash | Reconcile memory with the real files and git, recover from crashes by replay, check integrity, and handle several agents at once. |
| 2.6 | [#55](https://github.com/AdamMostofi/ADAM/issues/55) | Open the Archive | Generate the structured active context, deliver it in levels, and add the retrieval tools and CLI. |
| 2.7 | [#76](https://github.com/AdamMostofi/ADAM/issues/76) | Burn the Leak | Add secret purge and storage reporting, then pass the complete engine test suite. |

## Phase 3 — Carry the Memory ([#48](https://github.com/AdamMostofi/ADAM/issues/48))

Turn the engine into plugins for coding agents, and test whether it works.

| Stage | Issue | Name | What it does |
|---|---|---|---|
| 3.1 | [#56](https://github.com/AdamMostofi/ADAM/issues/56) | First Plugin | Define the adapter contract and ship the first automatic-capture plugin. |
| 3.2 | [#57](https://github.com/AdamMostofi/ADAM/issues/57) | Weigh the Thesis | Compare against compaction and git plus grep, then decide whether to continue. |
| 3.3 | [#58](https://github.com/AdamMostofi/ADAM/issues/58) | OpenCode Plugin | Add OpenCode, and prove one project's memory works across two agents. |
| 3.4 | [#59](https://github.com/AdamMostofi/ADAM/issues/59) | Pi Extension | Add a Pi extension, which also tests the contract against a tree-based session. |
| 3.5 | [#60](https://github.com/AdamMostofi/ADAM/issues/60) | Other Agents | Add plugins for agents with hooks, and an honest fallback for agents without them. |
| 3.6 | [#61](https://github.com/AdamMostofi/ADAM/issues/61) | Release the Engine | Move the engine to its own repo and publish it. |

## Phase 4 — The Citation Rite ([#16](https://github.com/AdamMostofi/ADAM/issues/16))

Connect ADAM to the engine and prove source-to-answer provenance.

| Stage | Issue | Name | What it does |
|---|---|---|---|
| 4.1 | [#46](https://github.com/AdamMostofi/ADAM/issues/46) | Connect the Engine | Put ADAM's storage behind one interface, backed by the engine. |
| 4.2 | [#24](https://github.com/AdamMostofi/ADAM/issues/24) | Open the Data-Vault | Ingest one Markdown file exactly once, with exact passage offsets and hashes. |
| 4.3 | [#34](https://github.com/AdamMostofi/ADAM/issues/34) | Speak Only the Evidence | Answer factual questions only from passages or proofs, and say when there is nothing. |
| 4.4 | [#77](https://github.com/AdamMostofi/ADAM/issues/77) | Revisit the Appraisal | Decide from measurements whether EQ still earns its place once answers come from evidence; if it does, address what keyword appraisal can't read (sarcasm, questions, litotes, context). |
| 4.5 | [#25](https://github.com/AdamMostofi/ADAM/issues/25) | Bear Witness | Show exact citations under the answer in the web chat. |
| 4.6 | [#35](https://github.com/AdamMostofi/ADAM/issues/35) | Trace the Thought | Record each chat turn as an inspectable trace, replacing the decorative status labels. |

## Phase 5 — The Book Study ([#17](https://github.com/AdamMostofi/ADAM/issues/17))

Teach ADAM to study a real book, with evidence that it works.

| Stage | Issue | Name | What it does |
|---|---|---|---|
| 5.1 | [#38](https://github.com/AdamMostofi/ADAM/issues/38) | Test the Reader | Measure whether claims can be extracted well enough, before building around it. |
| 5.2 | [#39](https://github.com/AdamMostofi/ADAM/issues/39) | Shape the Claim | Store who said what, under what conditions, before any are written. |
| 5.3 | [#40](https://github.com/AdamMostofi/ADAM/issues/40) | Keep the Score | Measure ADAM against plain search, and whether rereading helps. |
| 5.4 | [#62](https://github.com/AdamMostofi/ADAM/issues/62) | Widen the Library | Add more book formats with structural chunking and exact locations. |
| 5.5 | [#63](https://github.com/AdamMostofi/ADAM/issues/63) | Extract and Review | Extract candidate claims and require approval before they become facts. |
| 5.6 | [#64](https://github.com/AdamMostofi/ADAM/issues/64) | Study and Reread | Have ADAM test itself, find gaps, and reread when new knowledge calls for it. |
| 5.7 | [#41](https://github.com/AdamMostofi/ADAM/issues/41) | Close the Learning Loop | Turn repeated proofs into general, limited skills, and let chat teach facts with approval. |

## Phase 6 — The Ontology Web ([#18](https://github.com/AdamMostofi/ADAM/issues/18))

Connect knowledge across sources without making the first book a cage.

| Stage | Issue | Name | What it does |
|---|---|---|---|
| 6.1 | [#65](https://github.com/AdamMostofi/ADAM/issues/65) | Name the Concepts | Add the fixed meta-ontology and a revisable domain vocabulary. |
| 6.2 | [#66](https://github.com/AdamMostofi/ADAM/issues/66) | Build the Hierarchy | Check concept hierarchies and handle sources that disagree. |
| 6.3 | [#67](https://github.com/AdamMostofi/ADAM/issues/67) | Find the Isomorphisms | Find justified analogies across sources, and reject bad ones. |

## Phase 7 — The Tool Rites ([#19](https://github.com/AdamMostofi/ADAM/issues/19))

Give ADAM bounded, audited hands.

| Stage | Issue | Name | What it does |
|---|---|---|---|
| 7.1 | [#42](https://github.com/AdamMostofi/ADAM/issues/42) | Raise the Shields | Secure the API, and make sure text from books can never authorize an action. |
| 7.2 | [#68](https://github.com/AdamMostofi/ADAM/issues/68) | Register the Rites | Add the tool registry, audit log, and one safe read-only tool. |
| 7.3 | [#69](https://github.com/AdamMostofi/ADAM/issues/69) | Approve the Hands | Add approval-gated tools, and let others add their own. |
| 7.4 | [#70](https://github.com/AdamMostofi/ADAM/issues/70) | Remember the Procedures | Compile a reusable procedure after three real traces share its shape. |

## Phase 8 — The Imperial Console ([#20](https://github.com/AdamMostofi/ADAM/issues/20))

Expose the working study loop in the console.

| Stage | Issue | Name | What it does |
|---|---|---|---|
| 8.1 | [#71](https://github.com/AdamMostofi/ADAM/issues/71) | Library and Citations | View sources, passages, and citation paths in the console. |
| 8.2 | [#72](https://github.com/AdamMostofi/ADAM/issues/72) | Claim Review | Approve or reject claims in the console. |
| 8.3 | [#73](https://github.com/AdamMostofi/ADAM/issues/73) | Trace and Approvals | View traces, approve tools, and prove the full loop works end to end. |

## Phase 9 — Portable Release ([#49](https://github.com/AdamMostofi/ADAM/issues/49))

Package ADAM to run anywhere, and revisit agent clones.

| Stage | Issue | Name | What it does |
|---|---|---|---|
| 9.1 | [#45](https://github.com/AdamMostofi/ADAM/issues/45) | Clear the Licenses | Check model, code, and branding terms before distributing a build. |
| 9.2 | [#74](https://github.com/AdamMostofi/ADAM/issues/74) | Portable Runtime | Run the full system from a USB drive, within the memory budget. |
| 9.3 | [#75](https://github.com/AdamMostofi/ADAM/issues/75) | Clone the Mind | Re-check the clone idea against what the project has learned, then build it if justified. |
