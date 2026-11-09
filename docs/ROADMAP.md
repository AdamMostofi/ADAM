# ADAM Roadmap

This is the single order of work. Every stage has one previous and one next stage, and only one stage runs at a time. It replaces the phase numbers in older design docs, which remain useful as records of the reasoning.

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
