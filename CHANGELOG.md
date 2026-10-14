# Changelog

## V0.2 — Logical Kernel (Complete)

### Built
- 16 foundational logic rules in `kernel/foundations.py`
- Predicate-indexed agenda inference engine in `kernel/engine.py` (O(n) vs O(n^3))
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
- Replaced O(n^3) brute-force inference with O(n) predicate-indexed agenda
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
