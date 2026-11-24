# The storage contract

**Status:** Current. Stage 4.1, Connect the Engine ([#46](https://github.com/AdamMostofi/ADAM/issues/46)).

ADAM keeps its memory behind one contract, `memory.store_contract.FactStore`. Two stores implement it, and the
same contract tests run against both:

| Store | Where it keeps data | How to choose it |
|---|---|---|
| **Engine store** (`memory/engine_store.py`) | `adam_memory.engine/`, a [Yewtree](https://github.com/AdamMostofi/yewtree) store | The default |
| **Original store** (`memory/exact_store.py`) | `adam_memory.db`, SQLite schema 3 | `ADAM_STORE=exact` |

**Decision DSM.1** ([DECISIONS.md](../DECISIONS.md)): the engine stores and retrieves; what a fact means, and
what ADAM believes, stays in ADAM. Rules, inference, review and ontology never see the store.

## The boundary

Each rule below is checked by a test in `tests/contract/test_storage_boundary.py`:
- **One importer.** `memory/engine_store.py` is the only module in ADAM that imports the engine (`agent_memory`).
- **A separate kernel.** The kernel imports neither the engine nor the memory layer.
- **No reaching in.** The core (`interface/core.py`) and the web routes (`interface/web/app.py`) use
  `MemorySystem` only. They never touch a store, the vector index or the graph directly.
- **One caller.** Every store call is in `memory/system.py`, the `MemorySystem` facade.

## The operations ADAM uses

These were listed from the code: every call `MemorySystem` makes on its store. The contract holds exactly these.

| Group | Operation | Used by |
|---|---|---|
| Facts | `upsert(fact, proof_chain)` → (id, created); `store` | storing a fact, a classified fact, a fact with a proof |
| | `get(id)`, `get_with_proof(id)` | recall by id, the vector index's hits, `/api/facts/<id>` |
| | `has`, `all_keys` | `settle()`: which beliefs aren't stored yet |
| | `get_all`, `get_all_with_ids` | restore, the fact list, the vector index's rebuild |
| | `find_by_subject`, `find_by_predicate`, `find_by_object`, `get_user_facts` | related facts, the graph's connections |
| | `search_text(query)` | exact recall before semantic search |
| | `count`, `count_by_source` | the status panel |
| Supersession and origins | `supersede(fact, by_id)`, `superseded_ids()` | classifying an ambiguous fact; restore skips superseded facts |
| | `origins_of(id)`, `all_origins()` | per-source attribution (Stage 1.5); restore |
| Derivations | `store_derived(entries)` | `settle()` and storing inferred facts: facts and their derivations in one transaction |
| | `derivations_of(id)`, `trace(id)`, `render_trace(id)` | `/api/facts/<id>/trace`, proofs in replies |
| | `underived()`, `count_derivations()` | the integrity check that every derived fact has a derivation |
| Records | `put_record`, `put_records` (one transaction), `get_record`, `records`, `find_records` (by indexed field), `record_body` | the source library (Stage 4.2); skills and traces later: engine store only |
| The store | `backend`, `meta()`, `location()`, `close()` | the status panel, saves, tests |

**Rules every store keeps** (from Stages 1.4 and 1.5, now tested on both stores):
- **One fact per triple and source**, compared ignoring case and extra spaces. Storing it again keeps the higher
  confidence and the newer timestamp, and adds its origin. The first spelling is kept.
- **Ids count up** in the order facts are first stored, and carry on after a reopen.
- **A derived fact needs a derivation.** A batch with an underived fact, or an underived derived premise, is
  refused whole, and no id is used up.
- **The same derivation again keeps one record** with the higher confidence, whatever the order of its premises.
- **Nothing is deleted.** A superseded fact stays, and says what replaced it.

## How ADAM's data maps onto the engine

The engine store uses Yewtree's **generic records** (Yewtree 0.3.0, added for this stage: decision DSM.2). A
record has a caller-defined type, a key, versioned fields and an optional encrypted body. The engine stores,
versions, indexes and links records, and never interprets them.

| ADAM's data | Engine record | Key | Indexed fields |
|---|---|---|---|
| A fact | `adam.fact`: the integer id, triple, confidence, source, timestamp, text, origins, any proof chain, `superseded_by` | the fact key | id, key, subject, predicate, object, source |
| A derivation (Stage 1.4) | `adam.derivation`: rule, rule version, ordered premise ids, confidence, timestamp | conclusion, rule and premise set | id, conclusion id |
| Sources, passages, skills, traces | `adam.source`, `adam.passage`, `adam.skill`, `adam.trace`; a body (such as a book's text) is archived, compressed and encrypted | the caller's | the caller's |

**Derivations are engine links.** Each derivation record has a `supports` link to its conclusion and a
`based_on` link to each premise, with its position. The basis of these links is `recorded`, which means ADAM
states them as facts of its data. The engine doesn't infer them.

**Every change is a new version.** Storing a fact again with a higher confidence, or marking it superseded,
adds a version of its record. The engine's log keeps every version, hash-chained, so the store's whole history
can be verified (`EngineStore.verify()`).

**Writes are one transaction.** `store_derived` writes the facts, their derivations and their links in one
engine transaction, so a refused or failed batch stores nothing.

**The store is read once.** When it opens, the engine store reads every fact and derivation into an in-memory
index. Lookups and merges are served from that index, and every write updates it. This is why its reads are
faster than the SQLite store's. One ADAM process owns a store.

**Encryption.** The store is opened with project id `adam`, so its key is `adam.key` in the engine's key folder,
outside the repository. A copy of the store opens on the same machine; elsewhere it needs the key too.
`scripts/backup_stores.py` copies the store but not the key, and says so.

## Measurements

All are from `scripts/measure_store.py` and `scripts/measure_startup.py` (2026-11-24, Python 3.11.15, WSL). The
workload is a 3-level class hierarchy (2 roots, 10 middle classes, 50 leaves) with individuals in the leaves. The
embedding model is replaced by a fake, so only storage is timed.

**Memory (RAM).** Measured with `scripts/measure_memory.py`, with the real models
([memory-budget.md](memory-budget.md)); the budget is 400 MB:

| State | Original store | Engine store |
|---|---|---|
| `startup` | 127.6 MB | 136.8 MB |
| `chat` | 333.3 MB | 337.8 MB |
| `peak` | 336.1 MB | 338.5 MB |

**Within budget**, with 62 MB of headroom in `chat`.

**Startup**, the one latency figure recorded before this stage ([restart.md](restart.md)):

| Given facts | Recorded (Stage 1.6) | Original store, today | Engine store |
|---|---|---|---|
| 1,060 | 0.16 s | 0.11 s | 0.11 s |
| 5,060 | 0.77 s | 0.64 s | 0.71 s |
| 20,060 | 3.85 s | 3.05 s | 3.72 s |

**Within the recorded limit** at every size.

**Everything else**, with 2,060 given facts (4,112 conclusions stored with their derivations):

| | Original store | Engine store |
|---|---|---|
| Storing a fact, median (p95) | 0.81 ms (1.59) | 2.04 ms (3.90) |
| Settling: storing 4,112 conclusions and their derivations | 14.4 s | 21.0 s |
| Reopening (restore) | 0.60 s | 0.61 s |
| Get by id | 0.134 ms | 0.002 ms |
| Lookup by subject | 0.150 ms | 0.006 ms |
| Text search | 1.76 ms | 0.17 ms |
| Tracing a fact to its inputs | 3.69 ms | 0.06 ms |
| Disk | 15 MB | 95 MB |

Both stores ran one after the other on the same machine. Absolute times vary between runs by up to 1.5 times,
so compare the columns, not runs. With 260 given facts the proportions are the same: writes 0.61 against
1.61 ms, settling 0.54 against 1.68 s ([raw report](../measurements/2026-11-24-store-latency.json)). The raw
reports are in [docs/measurements](../measurements/), dated 2026-11-24.

**What this means:**
- **Writes are about two and a half times slower.** Each write is redacted for secrets, archived,
  hash-chained and applied to the engine's trees, and it is fsynced. A chat turn stores a handful of facts, so
  this costs a few milliseconds. Settling a large batch takes from 1.5 to 3 times as long.
- **Reads are faster**, because they come from the in-memory index.
- **The store is about six times larger on disk.** Every version of every record is kept, with its event, its
  index rows and its links. Disk isn't part of the budget ([memory-budget.md](memory-budget.md)).

**How it got here.** The first version took 5.5 ms per fact and 5.3 s to settle 512 conclusions. A profile
showed the time going to two record lookups per write and a database connection per call. The in-memory index,
and Yewtree's `put_records(..., check_unchanged=False)` for a caller that already knows what changed, brought
it to the figures above.

## Limits

- **No migration.** The engine store starts empty, and `adam_memory.db` is left as it is. Stores are disposable
  until study begins (#46, out of scope). To keep using an existing SQLite store, set `ADAM_STORE=exact`.
- **Skills and traces have a place but no users yet.** Sources and passages are written by the source library
  (Stage 4.2, [source-library.md](source-library.md)); the thought trace will write the first traces. Learned
  skills are still files in `skills/`.
- **`scripts/audit_store.py` audits the SQLite stores only.** For the engine store, use `EngineStore.verify()`.
- **One process per store.** The in-memory index isn't shared, so two ADAM processes on one store would each
  miss the other's writes.
