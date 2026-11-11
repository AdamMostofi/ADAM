# Kernel Layer 1 rules

The rules in `kernel/foundations.py`, as registered in `kernel/rules.py`
(`BUILTIN_RULES`). This file is the reference for what each rule does, how its
input is read, and which test checks it. It was written in Stage 1.1 (#27).

## How facts are read

Every fact is a triple `subject predicate object`. Two readings share the
same predicates.

- **Class reading.** `x is C` means x belongs to class C. `P implies Q` and
  `P all_are Q` mean every member of P is a member of Q. `x not_is C` means x
  does not belong to C.
- **Proposition reading.** The reserved object `true` turns a term into a
  statement: `rain is true` means rain holds, `rain not_is true` means it
  fails. Between propositions, `P implies Q` means P → Q.

Terms and reserved words:

| Term | Meaning |
|---|---|
| `true` | The object that marks a proposition. It is never a class: no rule treats `x is true` as membership of a class called "true". |
| `exists` | The subject of existential facts (`exists is dog`). It is never a proposition. |
| `not:p` | The negation of proposition p. Prefixes cancel in pairs, so `not:not:p` is `p`. Rules always write the canonical form: `not:p is true` is stored as `p not_is true`. |
| `arbitrary_T` | An arbitrary member of kind T, used by universal generalization. |

No rule derives a fact relating a term to itself with `is`, `implies`,
`all_are` or `equals`. Such facts are always true and carry no information,
and when `prove()` used `X is X` as an axiom, it "proved" `rain is wet` from
`rain implies wet`.

## The rules

There are 16 rules plus contradiction detection. Some rules are registered
more than once, once for each partner predicate they accept, which makes 23
registrations in total.

| Rule | Premises | Conclusion | Confidence |
|---|---|---|---|
| `modus_ponens` | `x is P` + `P implies Q`; or P holds + `P implies Q` | `x is Q`; or Q holds | product |
| `modus_tollens` | `x not_is Q` + `P implies Q`; or Q fails + `P implies Q` | `x not_is P`; or P fails | product × 0.9 |
| `transitivity` | `P implies Q` + `Q implies R` | `P implies R` | product |
| `subtype_transitivity` | `x is Y` + `Y implies Z` | `x implies Z` (subclass reading) | product |
| `is_transitivity` | `x is Y` + `Y is Z` | `x is Z` (subclass reading) | product |
| `universal_instantiation` | `X all_are Y` + `a is X` | `a is Y` | product |
| `existential_generalization` | `a is X` | `exists is X` | same |
| `universal_generalization` | `arbitrary_T is X` | `T all_are X` | × 0.9 |
| `equality_substitution` | `A equals B` + any fact using `is`, `not_is`, `implies`, `all_are`, `or` or `equals` | that fact with A and B swapped, in either position and either direction | product × 0.95 |
| `equality_symmetry` | `A equals B` | `B equals A` | same |
| `disjunctive_syllogism` | `A or B` + A fails (or B fails) | B holds (or A holds) | product |
| `de_morgan_and` | `A not_and B` | `not:A or not:B` | same |
| `de_morgan_or` | `A not_or B` | A fails, and B fails | same |
| `double_negation` | `P not_not true` (or `x not_not C`) | P holds (or `x is C`) | same |
| `conditional_proof` | `ctx assumes P` + `ctx derives Q`, sharing context ctx | `P implies Q` | product × 0.9 |
| `contradiction_detection` | `x is C` + `x not_is C` | `x contradiction C` (flagged; no rule takes it as a premise) | 1.0 |

`specificity_resolution` exists in `foundations.py` but isn't registered.
Stage 1.5 (#31) owns it.

Every propositional rule refuses premises built on the reserved words. For
example, `exists implies p` licenses nothing, and `true` is never a disjunct.

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

These are recorded as strict `xfail` tests in
`tests/integration/test_known_kernel_gaps.py`, so they fail loudly once fixed.

- **Stage 1.2 (#28):** beliefs depend on the order facts arrive in, and two
  terms can collide on the same belief key.
- **Stage 1.3 (#29):** `is` mixes membership and subclass, so `rex is dog`
  plus `dog is species` gives `rex is species`. `is_transitivity` and
  `subtype_transitivity` are only valid for the subclass reading.
- **Stage 1.4 (#30):** a stored belief's proof names only one premise.
  `prove()` already names all of them.
- **Stage 1.5 (#31):** exceptions such as the penguin case aren't resolved.

## Tests

| Test file | What it checks |
|---|---|
| `tests/unit/test_rule_soundness.py` | Exhaustive truth tables for every propositional rule, a set model for the subclass reading, and a membership model for instantiation rules. |
| `tests/unit/test_kernel_edge_cases.py` | Every registered rule fires through the engine; confidence stays in [0, 1]; unusual terms, self-reference, cycles and contradictions are handled. |
| `tests/integration/test_prove_agreement.py` | Generated fact sets, compared against a naive reference closure. `prove()` is sound and complete for what the rules derive, and `infer()` is sound. |
| `tests/integration/test_known_kernel_gaps.py` | Gaps owned by later stages. |

## Performance

Measured on 2026-11-11 against master, in milliseconds.

| Case | master `infer()` | `infer()` | master `prove()` | `prove()` |
|---|---|---|---|---|
| implies chain, 20 steps | 8 | 9 | missed the goal | 4 |
| implies chain, 50 steps | 173 | 184 | missed the goal | 12 |
| taxonomy, 10 × 10 | 12 | 21 | 0 | 3 |
| proposition chain, 30 steps | 17 | 36 | missed the goal | 7 |
| equality web, 15 terms | 39 | 55 | missed the goal | 12 |

The extra `infer()` time is new work: propositional modus ponens and modus
tollens, and substitution across six predicates instead of two. Most of the
remaining cost is the engine comparing each new fact with every fact of its
partner predicate. Stage 1.2 owns that.
