# Waking with memory

How a restarted ADAM rebuilds what it knew (Stage 1.6, #36).

## The rule

**DS1: SQLite is the source of truth; memory is rebuilt.** Nothing in the
engine or the graph is saved as a second truth. At startup,
`MemorySystem.restore()` rebuilds both from the store.

| What | How it comes back |
|---|---|
| Given facts | Every row that isn't derived (`source != deduced`) and isn't superseded goes into the engine, once for each of its origins. |
| Derived facts and their proofs | Re-derived by inference. They get the same derivation records as before, because the rules and the given facts are the same. |
| Conflicts and statuses (Stage 1.5) | Recomputed from the beliefs. They follow from the facts, so they aren't stored. |
| Origins (Stage 1.5) | Read from `fact_origins`. |
| The graph | Every row is replayed in ID order, as `store()` built it: its own edge, then its "related" connections. Replaying connects each fact to the distinct objects of the facts sharing its terms, which gives the same edges in linear time. |
| Learned skills | Loaded from `skills/` and registered after the facts. Since Stage 1.2, a rule added late gives the same beliefs as one added early. |
| Vectors | Already persistent (`adam_vectors.db`); nothing to rebuild. |
| Feelings (EQ) | Already persistent (`eq_state`). |

## Startup is read-only

Starting ADAM writes nothing, which a test checks byte for byte. So the
facts are the same before and after a restart, three restarts add zero
rows, and loading a save doesn't change it. Two things had to change:

- **The store stops rewriting on open.** Opening a store at the current
  schema version used to rewrite its schema metadata every time; it now
  returns at once.
- **Conclusions are stored on the next write.** Facts the store doesn't
  have yet, such as conclusions of a skill compiled since, or of facts
  stored without inference, are stored the next time ADAM writes. Each chat
  turn calls `MemorySystem.settle()`, which stores every belief the store is
  missing, with its derivations, in one transaction. Before, chat only
  stored what that turn's `infer()` returned, so anything found at startup
  was never stored.

`startup["not_yet_stored"]` counts those conclusions.

## Classified facts

`ADAMCore.classify_fact` (Stage 1.3) now does four things:
1. It stores the classified fact.
2. It marks the original ambiguous row `superseded_by` the new one, in the
   row's metadata. The row is kept, not deleted.
3. It removes the original's edge from the live graph.
4. It stores the conclusions the classification allows.

A restart doesn't give a superseded row to the engine, so the ambiguous fact
doesn't come back.

## Recalled facts

Chat adds recalled facts to the engine so inference can use them. A recalled
*derived* fact is no longer added, though. Giving it to the engine would mark
it as given, and it would then survive the retraction of its premises. It is
already in the engine as a consequence.

## Attention stays per session

Attention (`memory/attention.py`) ranks recalled facts by short-term
importance (STI), which decays at every recall, plus a small long-term part
(LTI, weighted 0.2). It is deliberately not persisted:

- **STI is meant to fade.** It describes the focus of the current
  conversation; carried across a restart, yesterday's topic would outrank
  today's.
- **LTI would cost a write per chat turn.** It changes on every recall, and
  today its effect is a tie-breaker. Persisting it would break the
  read-only startup unless it got its own store, so it is better decided
  together with the memory engine's relevance model (Phase 2), than bolted
  on here.

## Cost

Startup now runs inference until it finishes, up to
`STARTUP_INFERENCE_BUDGET` (200,000 steps), so a restarted ADAM knows
everything it knew. A pathological store stops at the budget with a warning
and continues during chat turns.

These are from `scripts/measure_startup.py`
(`docs/measurements/2026-11-13-startup.json`), on a taxonomy of individuals
in 50 leaf classes under a 3-level hierarchy. The embedding model is not
loaded, because restore doesn't embed.

| Given facts | Beliefs after restore | Graph edges | Startup |
|---|---|---|---|
| 1,060 | 3,173 | 2,120 | 0.16 s |
| 5,060 | 15,173 | 10,120 | 0.77 s |
| 20,060 | 60,173 | 40,120 | 3.85 s |

Before the linear replay, the 20,060-fact graph took 4.6 s on its own: the
old store-time connection logic is quadratic in facts that share an object.

## Limits

- **Edge confidence.** A graph edge carries the confidence its row has now.
  Before a restart, it carried the confidence the row had when first stored.
  Edge sets are equal; edge confidences can be higher after a restart.
- **The first write after a big restore can be large.** If many conclusions
  were never stored (for example, a store filled without inference), the
  first chat turn stores and embeds them all. In normal use, conclusions are
  stored as they are derived.
- **Removed:** `memory/persistence.py`, an unused second copy of
  save/load. `MemorySystem.load()` now opens the save and restores it like
  any start.
