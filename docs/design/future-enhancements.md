# Future Enhancements

## Joiner — Complex Rule Learning

**Status:** Deferred to V0.5+

**What it does:** Learns big rules (100+ literals) by joining small rules using SAT solvers.

**Why deferred:** High resource cost (50-100MB RAM, seconds to minutes per invocation). Popper handles 95% of patterns.

**When to activate:**
- Pattern has 5+ steps
- Pattern involves chaining 3+ rules together
- Popper times out or fails to find a pattern
- User manually triggers `system.learning.deep_learn()`

**Resource cost:**
- Dependency: `python-sat` (~5MB)
- Memory: 50-100MB when active
- Time: Seconds to minutes per invocation

**How it works:**
1. Popper tries first (fast, low cost)
2. If Popper fails, Complexity Detector checks if pattern is complex
3. If complex, Joiner runs (slow, high cost)
4. If not complex, store as macro-skill using foundation rules

## SAT Solver

**Status:** Deferred with Joiner

**What it does:** Finds combinations of small rules that together entail positive examples but not negative examples.

**Dependency:** `python-sat` (~5MB)

**Resource cost:** 50-100MB RAM when active, seconds to minutes per invocation.

## Structural Mapping Database

**Status:** Deferred (ATLAS database)

**What it does:** Pre-computed relational structures for 9000+ concepts.

**Why deferred:** ADAM builds its own structural representations using embeddings + relational structure extraction. The full ATLAS database (2M+ structures) is not needed for V0.4.

**When to consider:** If ADAM needs to make analogies across many domains without learning them first.
