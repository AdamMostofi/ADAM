# Changelog

## Stage 1.8 — Tell the Truth (#44)

- **README split.** The README is now split into "works today" (each
  capability with the test that shows it) and "planned" (by roadmap phase).
  - The headline is now a claim that can be shown: "a small, local
    reasoning system you can audit".
  - It names related work (the Learning Reader, NELL, Hyperon).
  - The corrected claims: semantic recall is MiniLM in SQLite (not
    LanceDB/bge-small); chat infers but doesn't prove; the learning loop
    isn't connected to chat; skills run as Layer 2 rules.
- **Roadmap restored.** `docs/ROADMAP.md` had lost Phases 3–9 in an edit on
  2026-11-09; it is restored and checked against every issue. The new
  Stage 4.4 (#77), revisiting EQ, makes 53 stages.
- **`docs/DECISIONS.md`** indexes every recorded decision and its outcome.
- **Status lines.** Every document now starts with one: current, proposed,
  superseded or historical.
- **Diagrams corrected:** 15 rules, no LanceDB, chat infers rather than
  proves, attention is per session. The stale V0.9/V1.0 timeline is removed.
- **USB guide** now names the real model (TinyChat15M GGUF, about 98 MB) and
  the SQLite vector store.
- **Banners.** "First Of It's Kind" is gone from the CLI and installer
  banners.
- **Tests.** `tests/unit/test_docs_truth.py` checks the README capabilities,
  the roadmap, status lines and links in CI. `tests/integration/test_cli.py`
  covers the CLI.

## Stage 1.7 — Steady the Appraisal (#37)

- **EQ matches whole words and phrases** (`learning/eq/lexicon.py`) instead
  of substrings, with clause-scoped negation, contrast ("but"), idioms and
  elongated words. "know", "unhappy", "whatever" and "economy" are no longer
  misread.
- **The manual override fires only on explicit, un-negated emotion words.**
- **Each chat turn is recorded once** (`chat()` used to repeat
  `process_input`'s recording).
- **EQ state is one row,** with the interaction history, instead of one new
  row per turn.
- **Accuracy:** the labelled set went from 25/38 to 38/38, and held-out
  probes from 10/24 to 20/24 (`scripts/measure_eq.py`). The remaining misses
  (sarcasm, questions, litotes) are documented.

## Stage 1.6 — Wake with Memory (#36)

- **Startup rebuilds everything from SQLite.** `MemorySystem.restore()`
  rebuilds the engine (given facts and origins, then inference to
  completion within a 200,000-step budget) and the graph (rows replayed in
  ID order). The rebuilt graph and beliefs match the ones before the
  restart.
- **Startup is read-only.** Opening a current store writes nothing, and
  three restarts add zero rows. Chat stores every belief the store is
  missing (`settle()`), including conclusions found at startup.
- **Classified facts stay classified.** The ambiguous original is marked
  superseded, never deleted.
- **Recalled derived facts** are no longer given back to the engine as if
  given.
- **Startup cost is measured:** 20,060 given facts take 3.85 s
  (`scripts/measure_startup.py`). Attention stays per session, and the
  reasons are recorded.
- **Removed** the unused `memory/persistence.py`, and the
  `'memories' in dir()` check in chat.

## Stage 1.5 — Hold the Contradiction (#31)

- **Defaults with exceptions.** `C typically D` and `C typically_not D`
  give conclusions that admit exceptions (`kernel/defaults.py`). Layer 1
  stays strict.
- **Conflicts are recorded state** (`kernel/conflicts.py`). Strict beats a
  default, a more specific default beats a general one, incomparable
  defaults are contested, and strict-against-strict is kept for review.
  Losers are marked `defeated`, `contested` or `unsupported`, never
  deleted, and queries return active beliefs.
- **APIs.** `engine.conflicts()` and `/api/conflicts`; `/api/stats`
  reports the real count.
- **Sources.** `Fact.origin` gives source attribution, and
  `engine.attribution()` lists it. The store keeps origins in
  `fact_origins` (schema 3).
- **Proofs.** `prove()` proves only from strict facts.

## Stage 1.4 — Keep the Chain (#30)

- **Derivation records.** Proofs are `Derivation` records naming the rule,
  its version, every premise and the confidence. Proof text is rendered from
  them.
- **Store schema 2.** A `derivations` table holds the records. Derived facts
  are stored with their derivations, and everything they rest on, in one
  transaction. A derived fact without a derivation is refused.
- **Walk-back.** `engine.explain()`, `ExactStore.trace()`,
  `MemorySystem.explain()` and `/api/facts/<id>/trace` walk any fact back to
  its inputs.
- **Learning from records.** `LearningEngine.learn_from_belief()` builds
  patterns with real premises.
- **Confidence defined.** The exposed value is the best support, and
  evidence counts distinct derivations.

## Stage 1.3 — Name the Bonds (#29)

- New predicates: `instance_of`, `not_instance_of` and `subclass_of`.
  `all_are` is stored as `subclass_of`, and properties are classes.
- `is_transitivity`, `subtype_transitivity` and `universal_instantiation`
  are replaced by `subclass_transitivity`, `inheritance` and `exclusion`.
  `rex instance_of dog` + `dog instance_of species` no longer gives
  `rex instance_of species`.
- A plain `x is C` is ambiguous and never guessed. It is listed by
  `engine.ambiguous()` and resolved with `engine.classify()`. Until then,
  only rules that are sound for both meanings use it. The web API flags,
  lists and classifies such facts.

## Stage 1.2 — Order the Agenda (#28)

- Inference gives the same beliefs whatever order facts arrive in: semi-naive
  evaluation applies binary rules in both premise positions.
- Partners are found through a (predicate, term) index instead of a scan.
- Beliefs are keyed by (subject, predicate, object), so differently split
  facts no longer collide.
- Confidence is the best support, and evidence counts distinct derivations.
  Both are independent of order.
- `retract()` rebuilds from given facts, and `add_rule()` applies a new rule
  to existing beliefs.
- The work budget is reported (`saturated`, `last_run`), and chat turns are
  budgeted.
- Measured, not O(n): a 160-step `is` chain takes 4.9 s, down from 63 s
  (`scripts/bench_kernel.py`, docs/design/kernel-rules.md).

## V0.2 — Logical Kernel (Complete)

### Built
- 16 foundational logic rules in `kernel/foundations.py`
- Predicate-indexed agenda inference engine in `kernel/engine.py` (the O(n) claim was wrong; see Stage 1.2)
- Knowledge graph with MultiDiGraph in `kernel/graph.py`
- Contradiction resolver in `kernel/contradictions.py`
- Unification with occurs check in `kernel/unification.py`
- Fact/Belief data models in `kernel/facts.py`

### Rules Implemented
- Modus Ponens, Modus Tollens, Transitivity
- Subtype Transitivity, Is Transitivity
- Universal Instantiation, Existential Generalization, Universal Generalization
- Equality Substitution (with symmetry, both directions)
- Disjunctive Syllogism
- Contradiction Detection
- De Morgan's AND/OR
- Double Negation
- Conditional Proof

### Optimizations
- Replaced brute-force inference with a predicate-indexed agenda (not O(n); measured numbers in docs/design/kernel-rules.md)
- Added RLock for thread safety
- Fixed graph self-loop handling with seen_edges deduplication
- Confidence propagation changed from min() to multiplicative

### Testing
- 162 tests passing across 5 categories:
  - Unit tests (13 files) — each rule tested individually
  - Integration tests (11 files) — multi-rule chains, engine features, graph, thread safety
  - Stress tests (3 files) — 100+ hop chains, 1000-node graphs
  - Fuzz tests (1 file) — malformed inputs, unicode, special characters
  - Property tests (1 file) — hypothesis-based invariant checking
- 3 red-team passes completed

### Documentation
- `docs/design/thread-safety.md` — RLock + actor-model solutions

---

## V0.3 — Memory System (Complete)

### Built
- `memory/exact_store.py` — SQLite + JSON hybrid storage (queryable, crash-safe, never-delete)
- `memory/semantic_index.py` — LanceDB + sentence-transformers embeddings (semantic search)
- `memory/connection_graph.py` — NetworkX auto-connection (exact + semantic similarity)
- `memory/system.py` — MemorySystem main API (store, recall, search, get_context, save/load)
- `memory/persistence.py` — save/load/export/import

### Features
- 3-layer storage: exact (SQLite), semantic (LanceDB), connection graph (NetworkX)
- Semantic similarity auto-connection (cosine similarity via embeddings)
- Thread-safe via RLock
- Persistence includes LanceDB data (save/load roundtrip)
- Error handling for corrupted/missing files
- Embedding quality verified (top 3 semantic search)
- Large-scale verified (1000+ facts in <23s)

### Issues Resolved
- #1: Auto-connection logic incomplete → added semantic similarity
- #2: Persistence edge cases → save/load includes LanceDB, error handling
- #4: No thread safety → added RLock
- #5: Model name mismatch → fixed default
- #7: Auto-connect duplicate edges → check before adding
- #8: Embedding quality not tested → verified top 3
- #9: Large-scale performance not tested → verified 1000+ facts

---

## V0.1 — Research & Specification (Complete)

- Meta AI's neuro-symbolic proposal analyzed
- Needle 2 + Tiny-LLM micro-architecture identified
- Cognitive architecture design finalized
- Two-layer kernel design (immutable foundation + acquired logic)
