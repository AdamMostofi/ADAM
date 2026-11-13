# Decisions

**Status:** Current. This index lists every recorded decision, what became of
it, and where the full reasoning lives. It was written in Stage 1.8 (#44),
and each stage that makes or settles a decision adds a row.

Some decision IDs were reused by different issues: DS1 (#36) and DS.1 (#34),
DD.1 (#38) and DD2.1 (#44), DE.1 (#37) and DE2.1 (#40). **The issue number
identifies a decision.**

Outcomes are as follows:
- **Adopted:** in force.
- **Settled:** a proposed decision that a stage resolved, possibly
  differently from the proposal.
- **Superseded:** replaced by a later decision.
- **Proposed:** not yet decided.
- **Open:** belongs to a stage not yet started.

## Phases

| Issue | Decision | Outcome |
|---|---|---|
| #15 | Phase 0 is a hard gate, not a parallel cleanup track. | Adopted; Phase 0 closed. |
| #26 | Repair the floor before anything is locked. | Adopted; Phase 1 in progress. |
| #47 | Build the memory engine inside this repo at `packages/agent-memory/`, with no imports from ADAM. | Adopted (Phase 2 not started). |
| #48 | One thin adapter per agent over one core; benchmark before expanding. | Adopted (Phase 3 not started). |
| #16 | Ship one citation slice, not the full cognitive substrate. | Adopted (Phase 4 not started). |
| #17, #18, #19, #20 | Each later phase stays in backlog until the one before exits. | Adopted. |

## Phase 0 — Stabilize the Vault

| Issue | ID | Decision | Outcome | Details |
|---|---|---|---|---|
| #21 | D0.1 | Back up before factory work. | Adopted. | `scripts/backup_stores.py` |
| #21 | D0.2 | The audit is read-only. | Adopted. | `scripts/audit_store.py` |
| #21 | D0.3 | Clean git history is part of the safety net. | Adopted. | |
| #22 | D1.1 | App factory, `create_app(core=None)`. | Adopted. | `interface/web/app.py` |
| #22 | D1.2 | Temporary stores and a fake embedder in tests. | Adopted. | `tests/conftest.py` |
| #22 | D1.3 | Production fingerprint guard. | Adopted. | `tests/store_guard.py` |
| #43 | DCI.1 | CI enforces the gates. | Adopted. | `.github/workflows/tests.yml` |
| #33 | DM.1 | 400 MB total while idle or chatting; studying is measured separately. | Adopted by the owner, 2026-11-09. | [memory-budget.md](design/memory-budget.md) |
| #33 | D2.4 | The earlier memory target. | Superseded by DM.1. | |
| #32 | DV.1 | Choose the vector backend from measurements, with bounded growth required. | Adopted: numpy over SQLite. | [vector-index.md](design/vector-index.md) |
| #32 | D2.3 | Lock the embedding model only after a benchmark. | Settled: MiniLM-L6-v2 int8, pinned revision. | [vector-index.md](design/vector-index.md) |
| #23 | D2.1 | Reset and rebuild rather than dedupe in place. | Adopted. | `scripts/reset_store.py` |
| #23 | D2.2 | Dedupe on write: a unique key plus upsert. | Adopted. | `memory/exact_store.py` |

## Phase 1 — Repair the Floor

| Issue | ID | Decision | Outcome | Details |
|---|---|---|---|---|
| #27 | DR1.1 | Prove soundness independently of examples. | Adopted: truth tables, then a typed set model. | `tests/unit/test_rule_soundness.py` |
| #27 | DR1.2 | Represent negated propositions explicitly. | Settled: `not:` terms, cancelled in pairs, canonical `p not_is true`. | [kernel-rules.md](design/kernel-rules.md) |
| #28 | DR2.1 | Order independence is a tested invariant. | Adopted. | `tests/integration/test_order_independence.py` |
| #28 | DR2.2 | Forward on demand, not full saturation. | Settled **against** the proposal. On-demand transitivity loses real conclusions, so inference stays eager but incremental and budgeted. | [kernel-rules.md](design/kernel-rules.md) |
| #29 | DR3.1 | Split membership from subclassing in the kernel now. | Adopted: `instance_of`, `subclass_of`. | [kernel-rules.md](design/kernel-rules.md) |
| #29 | DR3.2 | Don't guess an ambiguous `is`. | Settled: kept, listed for review, resolved with `classify()`, used only by rules sound under both readings. | [kernel-rules.md](design/kernel-rules.md) |
| #30 | DR4.1 | The record is the truth; English is a projection. | Adopted: derivation records. Supersedes the "proof chains as strings" note in [HYPERON_ANALYSIS.md](HYPERON_ANALYSIS.md). | [kernel-rules.md](design/kernel-rules.md) |
| #30 | — | Which confidence the API exposes. | Settled: best support, with evidence counting distinct derivations. Supersedes PLN revision in [HYPERON_ANALYSIS.md](HYPERON_ANALYSIS.md). | [kernel-rules.md](design/kernel-rules.md) |
| #31 | DR5.1 | Contradiction is state, not failure. | Adopted. | `kernel/conflicts.py` |
| #31 | DR5.2 | Keep the logic floor strict. | Settled: defaults (`typically`) live outside Layer 1. | `kernel/defaults.py` |
| #36 | DS1 | SQLite is the source; memory is rebuilt at startup. | Adopted, and startup is read-only. | [restart.md](design/restart.md) |
| #36 | — | Persist attention? | Settled: per session, with reasons recorded. | [restart.md](design/restart.md) |
| #37 | DE.1 | Fix EQ first; question its value later. | Adopted; the review is #77. | [eq-appraisal.md](design/eq-appraisal.md) |
| #44 | DD2.1 | The README describes what runs. | Settled: "works today" (each with a test) and "planned", with a demonstrable headline. **The owner may revise the headline.** | [README.md](../README.md) |

## Later phases (not started)

| Issue | ID | Decision | Outcome |
|---|---|---|---|
| #46 | DSM.1 | Generic engine; ADAM's meanings stay in ADAM. | Adopted. |
| #24 | D3.1–D3.4 | Markdown first, SQLite FTS5 retrieval, CLI ingest only, console naming. | Adopted. |
| #34 | DS.1 | Templates before generation for facts. | Proposed (owner's call). |
| #77 | DE.2 | Decide EQ's value before adding sophistication. | Adopted. |
| #25 | D4.1–D4.4 | Additive citations API, web chat only, console naming, evidence gate. | Adopted. |
| #35 | DT.1 | Start the thought trace small; grow node types with use. | Adopted. |
| #38 | DD.1, DD.2 | Test the reader before building around it, with a human-authored gold set. | Adopted. |
| #39 | DC.1 | Claims sit above facts, rather than rewriting `Fact`. | Proposed. |
| #40 | DE2.1 | Compare against a simple baseline. | Adopted. |
| #41 | DL.1 | Explanation-based learning, gated. | Adopted. |
| #42 | DSEC.1 | Trust comes from the user channel only. | Adopted. |

The memory engine's own design decisions (D1–D8) are in
[the engine design](design/2026-11-06-agent-memory-engine.md).
