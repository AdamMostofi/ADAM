# Kernel Layer 1 rules

The rules in `kernel/foundations.py`, as registered in `kernel/rules.py`
(`BUILTIN_RULES`). This file is the reference for what each rule does, how its
input is read, and which test checks it. It was written in Stage 1.1 (#27).

## How facts are read

Every fact is a triple `subject predicate object`.

- **Classes (Stage 1.3, #29).**
  - `x instance_of C`: x is a member of class C.
  - `x not_instance_of C`: x is not a member.
  - `C subclass_of D`: every member of C is a member of D.
  - `all_are` is another name for `subclass_of` and is stored as `subclass_of`.
  - `P implies Q` between classes also means every P is a Q.
  - Properties are classes, so "socrates is mortal" is
    `socrates instance_of mortal`.
- **Propositions.** The reserved object `true` turns a term into a statement:
  `rain is true` means rain holds, and `rain not_is true` means it fails.
  Between propositions, `P implies Q` means P → Q.
- **Ambiguous `is`.** `x is C`, with C anything other than `true`, could mean
  `instance_of` or `subclass_of`: "rex is dog" against "dog is mammal". The
  kernel never guesses (DR3.2).
  - The fact is kept, and `engine.ambiguous()` lists it for review.
    `engine.classify(fact, "instance_of" | "subclass_of")` resolves it. In
    the web UI, `/api/facts` flags it, `/api/ambiguous` lists it, and
    `/api/classify` resolves it.
  - Until then, only rules that are sound under both readings use it. For
    example, `x is C` + `C subclass_of D` gives `x is D`, which holds whether
    x is a member or a subclass of C.
  - No rule chains two `is` facts, so `rex is dog` + `dog is species` gives
    nothing. That was the bug Stage 1.3 fixed.
- Every named class is assumed to be non-empty, so `x is C` under either
  reading means something is a C.

Terms and reserved words:

| Term | Meaning |
|---|---|
| `true` | The object that marks a proposition. It is never a class: no rule treats `x is true` as membership of a class called "true". |
| `exists` | The subject of existential facts (`exists instance_of dog`). It is never a proposition. |
| `not:p` | The negation of proposition p. Prefixes cancel in pairs, so `not:not:p` is `p`. Rules always write the canonical form: `not:p is true` is stored as `p not_is true`. |
| `arbitrary_T` | An arbitrary member of kind T, used by universal generalization. It names an individual, so `arbitrary_T is X` is stored as `arbitrary_T instance_of X`. |

No rule derives a fact relating a term to itself with `is`, `implies`,
`subclass_of` or `equals`. Such facts are always true and carry no information,
and when `prove()` used `X is X` as an axiom, it "proved" `rain is wet` from
`rain implies wet`.

## The rules

There are 15 rules plus contradiction detection. Some rules are registered
more than once, once for each pair of predicates they accept, which makes 34
registrations in total. (The Stage 1.1 and 1.2 versions of this file said
"16 rules plus contradiction detection", but their table had 15 rules too.)

| Rule | Premises | Conclusion | Confidence |
|---|---|---|---|
| `modus_ponens` | P holds + `P implies Q` | Q holds | product |
| `modus_tollens` | Q fails + `P implies Q` | P fails | product × 0.9 |
| `transitivity` | `P implies Q` + `Q implies R` | `P implies R` | product |
| `subclass_transitivity` | `A subclass_of B` + `B subclass_of C`; either may be `implies` (not both) | `A subclass_of C` | product |
| `inheritance` | `x instance_of C` (or ambiguous `x is C`) + `C subclass_of D` (or `C implies D`) | `x instance_of D` (or `x is D`) | product |
| `exclusion` | `x not_instance_of D` (or ambiguous `x not_is D`) + `C subclass_of D` (or `C implies D`) | `x not_instance_of C` (or `x not_is C`) | product × 0.9 |
| `existential_generalization` | `a instance_of X` (or ambiguous `a is X`) | `exists instance_of X` | same |
| `universal_generalization` | `arbitrary_T instance_of X` | `T subclass_of X` | × 0.9 |
| `equality_substitution` | `A equals B` + any fact using `is`, `not_is`, `instance_of`, `not_instance_of`, `subclass_of`, `implies`, `or` or `equals` | that fact with A and B swapped, in either position and either direction | product × 0.95 |
| `equality_symmetry` | `A equals B` | `B equals A` | same |
| `disjunctive_syllogism` | `A or B` + A fails (or B fails) | B holds (or A holds) | product |
| `de_morgan_and` | `A not_and B` | `not:A or not:B` | same |
| `de_morgan_or` | `A not_or B` | A fails, and B fails | same |
| `double_negation` | `P not_not true` (or `x not_not C`) | P holds (or ambiguous `x is C`) | same |
| `conditional_proof` | `ctx assumes P` + `ctx derives Q`, sharing context ctx | `P implies Q` | product × 0.9 |
| `contradiction_detection` | `x is C` + `x not_is C`, or `x instance_of C` + `x not_instance_of C` | `x contradiction C` (flagged; no rule takes it as a premise) | 1.0 |

Exceptions are not Layer 1 rules. Defaults and conflict resolution are
described under "Conflicts and defaults (Stage 1.5)" below.

Every propositional rule refuses premises built on the reserved words. For
example, `exists implies p` licenses nothing, and `true` is never a disjunct.

### Changed in Stage 1.3 (#29)

| Before | After | Why |
|---|---|---|
| `is_transitivity`: `x is Y` + `Y is Z` gives `x is Z` | Removed. `subclass_transitivity` chains `subclass_of`. | `rex is dog` + `dog is species` gave `rex is species`. Chaining is only valid for subclass-of. |
| `subtype_transitivity`: `x is Y` + `Y implies Z` gives `x implies Z` | Replaced by `subclass_transitivity`. | It was only valid when "x is Y" meant subclass. |
| `universal_instantiation` on `all_are` | Removed. `all_are` is now `subclass_of`, and `inheritance` covers it. | Two rules for one inference would count the same derivation twice as evidence. |
| The class forms of `modus_ponens` and `modus_tollens` | Moved into `inheritance` and `exclusion`. | Same reason. Both rules are now purely propositional. |
| `existential_generalization` gave `exists is X` | It gives `exists instance_of X`. | "Something is an X" is membership. |

`tests/unit/test_rule_soundness.py` checks every class rule in a typed
model: individuals are elements, classes are non-empty sets, and an
ambiguous `is` means membership for an individual and subset for a class.
Rules can't tell the two readings apart, so passing means every rule is
sound under both.

## What was wrong before Stage 1.1

| Rule | Defect | Fix |
|---|---|---|
| `de_morgan_and` | `rain not_and cold` asserted both `rain not_is true` and `cold not_is true`. | It now gives `not:rain or not:cold`. |
| `conditional_proof` | It paired an assumption and a derivation from unrelated contexts (`moon assumes x` + `tax derives banana` gave `moon implies banana`). | It requires the same context. |
| `disjunctive_syllogism` | Any negated fact about A licensed B (`a or b` + `a not_is blue` gave `b`). | It requires that A itself fails, and handles both disjuncts. |
| `universal_generalization` | It was registered on `all_are`, so it never fired, and its output subject was the meaningless `all_c`. | It is triggered by `arbitrary_T is X` and gives `T all_are X`. |
| `modus_ponens`, `modus_tollens` | They had no propositional form: `rain is true` + `rain implies wet` gave nothing. | Both forms are supported, including negated terms. |
| `double_negation` | Its output was not in canonical form. | It writes canonical literals. |
| `equality_substitution` | It only rewrote `is` and `equals` facts, and nothing gave symmetry. | It now covers six predicates, and `equality_symmetry` was added. |
| All rules | Reflexive facts (`x is x`) and `true` used as a class leaked into conclusions. | Both are guarded. |
| `prove()` | It used a separate backward search with a reflexive axiom, so it disagreed with `infer()`. | It now saturates the facts connected to the goal using these same rules (see `kernel/prove.py`). |

### Second red-team pass

These were found after the fixes above. Tests are in
`tests/unit/test_kernel_red_team_pass2.py`.

| Defect | Fix |
|---|---|
| Facts written in a non-canonical form, such as `not:rain is true` or `not:not:rain is true`, were invisible to the propositional rules. `rain is true` plus `not:rain is true` wasn't even flagged as a contradiction. | `canonical_fact()` rewrites every fact when it enters the engine and every rule output, so one statement is always one belief. `prove()` also canonicalizes its goal. |
| `retract()` rebuilt beliefs only from `Source.USER` facts, so every retract silently dropped all `LEARNED` and `INFERRED` facts. | It keeps every fact that wasn't derived. |
| `infer()` stopped at `max_iterations` without saying so. A 200-step chain left 7,723 facts queued. | It sets `engine.saturated = False` and logs a warning. Calling `infer()` again continues the work. |

## Listed in DESIGN.md but not rules

| Item | Status |
|---|---|
| Reflexivity (A = A) | True but not stored. No rule derives it, because it carries no information and using it as a premise caused false proofs. |
| Transitivity of = | Not a separate rule. `A equals B` + `B equals C` gives `A equals C` through substitution. |
| Transitivity of >, <, >= | Not implemented. The kernel has no comparison predicates. |
| Negation as failure | Not implemented, deliberately. Assuming "not P" because P wasn't found is unsound when knowledge is incomplete. If it is added, it belongs in query answers marked as an assumption, not in stored beliefs. |
| Unification | Not an inference rule. `kernel/unification.py` matches `?variable` patterns for queries. |
| AND | There is no `and` predicate. A conjunction is stored as separate facts. |

## Known gaps owned by later stages

From Stage 1.1 to 1.5, every gap found had a strict `xfail` test in
`tests/integration/test_known_kernel_gaps.py`. All of those are fixed, so
that file is gone. What remains is recorded on its issue:

- None at present. Stage 1.6 (#36) closed the last one: a classified
  fact now supersedes its ambiguous original, and a restart rebuilds the
  engine (with conflicts and origins) and the graph from the store. See
  docs/design/restart.md.

## Tests

| Test file | What it checks |
|---|---|
| `tests/unit/test_rule_soundness.py` | Exhaustive truth tables for every propositional rule, and a typed model (individuals and classes) for every class rule, under both readings of an ambiguous `is`. |
| `tests/integration/test_derivations.py` | Derivation records in the engine and the store. Every stored derived fact walks back to its inputs (generated fact sets), repeats add nothing, multi-word terms round-trip, the schema 1 migration works, and failed writes store nothing. |
| `tests/unit/test_class_rules.py` | `instance_of`, `subclass_of`, inheritance, exclusion, the ambiguous-`is` rules, and `classify()`. |
| `tests/unit/test_kernel_edge_cases.py` | Every registered rule fires through the engine; confidence stays in [0, 1]; unusual terms, self-reference, cycles and contradictions are handled. |
| `tests/integration/test_prove_agreement.py` | Generated fact sets, compared against a naive reference closure. `prove()` is sound and complete for what the rules derive, and `infer()` is sound. |
| `tests/integration/test_conflicts.py` | The penguin case, both through a more specific default and through direct evidence; the Nixon diamond; strict contradictions; unsupported consequences; restoring on retract; source attribution; and statuses and conflicts that don't depend on fact order. |

## Conflicts and defaults (Stage 1.5, #31)

**DR5.2: the floor stays strict.** Layer 1 rules are deductive and are
never defeated. General rules that admit exceptions are *defaults*
(`kernel/defaults.py`):
- `C typically D` ("bird typically flier");
- `C typically_not D` ("penguin typically_not flier").

`default_inheritance` and `default_exclusion` apply them to members. Their
conclusions are defeasible, and so is anything derived from them.

**DR5.1: a contradiction is state, not failure.** After inference,
`kernel/conflicts.py` looks at every pair of contradicting beliefs, `x
instance_of C` against `x not_instance_of C` (the same for an ambiguous
`is`). It records a `Conflict` with:
- both beliefs;
- all their derivations;
- the sources behind each side;
- the resolution.

| Sides | Resolution | Result |
|---|---|---|
| Both strict | `unresolved` | Nothing is withdrawn; the conflict is recorded for review. |
| Strict against a default | `strict_beats_default` | The default side is defeated. Evidence about the individual ("pingu not_instance_of flier") is strict. |
| Two defaults, one about a strict subclass of the other's class | `more_specific_default` | The less specific side is defeated (penguin ⊂ bird). |
| Two defaults, neither more specific | `contested` | Both sides are withheld (the Nixon diamond). |

**Statuses.** Nothing is deleted. Every belief has a status:
- `active`;
- `defeated`, if it lost a conflict;
- `contested`;
- `unsupported`, if every derivation rests on something not active.

`query()` and `query_pattern()` return only active beliefs, and
`query(..., include_inactive=True)` returns all of them. A given fact is
never defeated, so conflicts never remove source-backed evidence.
Statuses follow from the beliefs alone, so they don't depend on fact
order (checked with generated fact sets). Retracting the evidence that
defeated a default brings back its conclusion.

**APIs.**
- `engine.conflicts()`, `engine.status()`, `/api/conflicts`, and the
  `contradictions` count in `/api/stats`, which was always 0 before.
- `ContradictionResolver.get_contradictions()` now reports the engine's
  conflicts.
- `prove()` proves only from strict facts: a default conclusion is not a
  proof.

**Sources.** `Fact.origin` names where a fact came from: a book, a person
or a URL. A belief keeps every origin it was given by, and
`engine.attribution()` lists the origins of everything a belief rests on.
Two sources that disagree are recorded as a conflict, with each side
attributed to its own source. Neither source's facts are changed. The
store keeps origins in the `fact_origins` table (schema 3).

**Limit.** Conflicts are resolved in one pass. A conflict between two
beliefs that are each only defeasible through longer chains (not directly
from a default) is `contested`, not resolved by specificity.

## Proofs (Stage 1.4, #30)

DR4.1: the record is the truth, and English is a projection. Every derivation
is a `Derivation` record (`kernel/facts.py`) with these fields:
- **`rule`:** the rule name, for example `inheritance_implies` or
  `skill:mortality`;
- **`rule_version`:** `KERNEL_RULES_VERSION` for Layer 1, or the compile
  time of a learned skill;
- **`premises`:** the premise keys, in the order the rule took them;
- **`confidence`:** what this derivation gives, using the best confidence of
  each premise.

In memory:
- **Records per belief.** `Belief.proofs` lists a belief's records, up to 16.
  Two derivations are the same when they use the same rule and the same
  premise set, so repeating one adds no record and no evidence; it only keeps
  the higher confidence.
- **Text is rendered.** `Belief.proof_chain` and `engine.get_trace()` render
  text from the records.
- **Derived means `DEDUCED`.** Every conclusion's source is `DEDUCED`, even
  when a learned skill made it. The rule name records which rule did.
- **Walk-back.** `engine.explain(s, p, o)` walks a belief back to the given
  facts it rests on, premises first, and `render_explanation()` turns that
  into text. The walk is well-founded: a step is used only once some
  derivation of it has every premise explained, so cycles such as
  `a equals b` and `b equals a` can't trap it.

In the store (schema 2):
- **The `derivations` table.** Each row holds the conclusion ID, the rule
  and its version, the ordered premise IDs, the premise set, the confidence
  and a timestamp. It is unique on (conclusion, rule, premise set).
- **One transaction.** `MemorySystem.store_beliefs()` stores beliefs, their
  derivations and everything they rest on together. Chat uses it through
  `store_inferred()`.
- **No derived fact without a derivation.** A derived fact can't be stored
  without at least one derivation (`UnderivedFactError`), and a derived
  premise must be stored with its own derivations.
- **Walk-back.** `ExactStore.trace(id)` and `MemorySystem.explain(id)` walk a
  stored fact back to its inputs, using the same well-founded walk. The web
  API offers it as `/api/facts/<id>/trace`, and `/api/facts` now includes
  IDs.
- **Migration.** A schema 1 store migrates in place. Its rows are kept, and
  any derived rows without derivations are listed by `underived()` and by
  `scripts/audit_store.py`, never deleted. The old `proof_chain` column is
  no longer written.

Learning:
- `LearningEngine.learn_from_belief()` builds patterns from the records,
  with their real premises. Multi-word terms like `new york` round-trip
  exactly.
- The old text path, `learn_from_proof()`, is kept for compatibility. It
  still only knows conclusions, because text can't say where a multi-word
  term ends.

**Confidence exposed by every API:** a belief's best support, meaning its
most confident derivation or its highest given value. `evidence` counts
distinct derivations separately. This supersedes the PLN revision plan in
`docs/HYPERON_ANALYSIS.md`. Different derivations of one conclusion usually
share premises, so revising them together counts the same evidence twice,
and the result depended on arrival order (Stage 1.2).

**Cost:** keeping up to 16 records per belief makes `infer()` about 10–18%
slower than Stage 1.3 on derivation-heavy cases. That is ten interleaved
runs each: `subclass_of` chain of 80, +16%; equality web of 15, +11% to
+17%. Proposition chains and taxonomies are unchanged.

## The engine (Stage 1.2, #28)

`kernel/engine.py` computes the same beliefs whatever order facts arrive in.
`tests/integration/test_order_independence.py` checks this with Hypothesis.
For generated fact sets, it compares a single batch, one fact at a time,
random permutations, and random chunks with inference in between. It also
checks that saturated inference equals the reference closure exactly, and
that retracting a fact gives the same state as never adding it.

- **Semi-naive evaluation.** When a fact leaves the agenda, every binary
  rule is applied with it in both premise positions, against the facts
  already processed. Each pair of facts is therefore combined exactly once,
  when the later of the two is processed. Before this stage, rules fired
  only when the trigger fact was the newer one, so `fire implies hot`
  followed by `x is fire` derived nothing.
- **Term index.** Layer 1 rules only combine facts that share a term, so
  partners are looked up by `(predicate, term)`. The old engine scanned every
  fact with the partner predicate, and every `is` and `not_is` fact for
  contradictions. Layer 2 rules (compiled skills) make no such promise, so
  they still scan.
- **Keys.** Beliefs are keyed by the `(subject, predicate, object)` tuple.
  Before, `new york is city` and `new` / `york is` / `city` collapsed into
  one belief.
- **Confidence and evidence.** A belief's confidence is its best support,
  either a derivation or the highest given value. When it rises, the belief
  is processed again so its consequences rise too. `evidence` counts
  distinct derivations, up to 16, plus one if the belief was given.
  Previously, PLN revision folded in a second derivation only when it
  arrived in a later `infer()` pass. The same facts in one batch gave a
  different confidence. The derivations also shared premises, so revision
  double-counted evidence.
- **Given facts.** `Belief.given` and `Belief.given_confidence` record what
  was given, as opposed to derived. `retract()` rebuilds from exactly these
  facts. Before, it rebuilt from the `Source` tag, so learned skill
  conclusions survived the retraction of their premises.
- **`add_rule`.** A new layer 2 rule is applied to the beliefs already
  known, so a late rule gives the same result as an early one.
- **Budget.** `infer(max_iterations)` returns once that many agenda entries
  have been processed. `saturated` and `last_run` (iterations, rule
  applications, beliefs added) report whether work remains, and the next
  call continues it. Facts about things are processed before `implies`
  facts, so a budgeted run reaches conclusions about things first. A chat
  turn processes at most 2,000 entries (`interface/core.py`).

### Eager or on demand (DR2.2)

Inference stays eager and complete. On-demand `transitivity` (`P implies Q`
+ `Q implies R`) was tested against the reference evaluator and rejected,
because it loses real conclusions. `a not_not b` + `b implies a` +
`a implies c` gives `a is c` only through the derived `b implies c`: the
other route needs `a is a`, which no rule derives. The cost is bounded
instead:
- inference is incremental, so a chat turn only pays for the consequences
  of what it added;
- the budget stops long runs;
- the processing order puts conclusions about things first;
- `prove()` answers single questions without saturating everything.

Saturating long chains is still cubic: a 320-step `is` chain has 51,680
beliefs and takes about 40 s. Persisting fewer derived facts is a question
for the memory stages.

## Performance

Stage 1.3 kept the costs of Stage 1.2. I measured both kernels side by side,
five runs each, on the same machine, which was more loaded than for the
table below:
- proposition chain, 30: unchanged (0.080 s against 0.079 s);
- equality web, 15: 18% slower (0.130 s against 0.110 s), because
  substitution now covers eight predicates instead of six;
- an 80-step `subclass_of` chain against Stage 1.2's `is` chain: 13% slower
  (1.25 s against 1.11 s).

The worst case is now a `subclass_of` chain, because an ambiguous `is` chain
no longer combines. Timings are in
`docs/measurements/2026-11-11-kernel-benchmark-stage-1.3.json`.

Measured on 2026-11-11 with `scripts/bench_kernel.py --compare d4e6d6e`
(the kernel before Stage 1.1). Each case runs in a fresh process.
`docs/measurements/2026-11-11-kernel-benchmark.json` has the full report.

| Case | Before 1.1, batch | Before 1.1, one at a time | Now, batch | Now, one at a time |
|---|---|---|---|---|
| `is` chain, 40 | 0.105 s, 860 beliefs | 0.002 s, **80 beliefs** | 0.095 s, 860 | 0.085 s, 860 |
| `is` chain, 80 | 2.28 s, 3,320 | 0.004 s, **160** | 0.63 s, 3,320 | 0.50 s, 3,320 |
| `is` chain, 160 | 63.3 s, 13,040 | 0.016 s, **320** | 4.95 s, 13,040 | 4.03 s, 13,040 |
| `implies` chain, 50 | 0.22 s, 1,477 | 0.004 s, **152** | 0.17 s, 1,427 | 0.17 s, 1,427 |
| taxonomy, 10 × 10 | 0.017 s, 322 | 0.008 s, **221** | 0.029 s, 321 | 0.028 s, 321 |
| proposition chain, 30 | 0.022 s, 467 | 0.0003 s, **32** | 0.041 s, 496 | 0.040 s, 496 |
| equality web, 15 | 0.045 s, 273 | 0.032 s, 258 | 0.061 s, 257 | 0.062 s, 257 |

The old engine was fast one fact at a time only because it skipped most
conclusions (the numbers in bold). #28 recorded 142.71 s for the 160-step
chain on Windows.

### Stage 1.1 measurements

Measured on 2026-11-11 against master, in milliseconds.

| Case | master `infer()` | `infer()` | master `prove()` | `prove()` |
|---|---|---|---|---|
| implies chain, 20 steps | 8 | 9 | missed the goal | 4 |
| implies chain, 50 steps | 173 | 184 | missed the goal | 12 |
| taxonomy, 10 × 10 | 12 | 21 | 0 | 3 |
| proposition chain, 30 steps | 17 | 36 | missed the goal | 7 |
| equality web, 15 terms | 39 | 55 | missed the goal | 12 |

The extra `infer()` time is new work: propositional modus ponens and modus
tollens, and substitution across six predicates instead of two. Stage 1.2
removed the scan over every fact of the partner predicate (see above).
