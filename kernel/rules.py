"""Declarative inference rules.

Hyperon/MeTTa treats rules as data: a rule is just another atom, so learning
a rule and writing one are the same act. ADAM keeps its immutable Layer 1
rules in `kernel/foundations.py`, but exposes them here through one uniform
`Rule` table. The engine walks this table instead of hardcoding an if-chain,
and layer-2 learned rules (compiled skills) can be appended at runtime via
`InferenceEngine.add_rule`.

Layer 1 stays immutable: `BUILTIN_RULES` is fixed at import time. A rule
function can appear more than once with different predicate pairs, so it
fires whatever predicate its partner fact has.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from kernel import foundations
from kernel.facts import Fact

RuleResult = Fact | list[Fact] | None
RuleFn = Callable[..., RuleResult]

# Predicates a fact about an equal term can carry; equality substitution pairs with each.
SUBSTITUTABLE = ("is", "not_is", "implies", "all_are", "or", "equals")


@dataclass(frozen=True)
class Rule:
    """A named inference rule keyed by the predicates it consumes.

    `trigger` is the predicate of the fact being processed. `partner` is the
    predicate of the indexed fact it is combined with, or None for unary
    rules. `apply` is called as apply(fact) when unary and apply(fact, other)
    when binary, returning zero or more results.
    """

    name: str
    trigger: str
    partner: str | None
    apply: RuleFn


BUILTIN_RULES: tuple[Rule, ...] = (
    Rule("modus_ponens", "implies", "is", foundations.modus_ponens),
    Rule("modus_ponens_negated", "implies", "not_is", foundations.modus_ponens),
    Rule("transitivity", "implies", "implies", foundations.transitivity),
    Rule("modus_tollens", "implies", "not_is", foundations.modus_tollens),
    Rule("modus_tollens_negated", "implies", "is", foundations.modus_tollens),
    Rule("existential_generalization", "is", None, foundations.existential_generalization),
    Rule("subtype_transitivity", "is", "implies", foundations.subtype_transitivity),
    Rule("is_transitivity", "is", "is", foundations.is_transitivity),
    Rule("universal_instantiation", "all_are", "is", foundations.universal_instantiation),
    Rule("universal_generalization", "is", None, foundations.universal_generalization),
    *(Rule(f"equality_substitution_{p}", "equals", p, foundations.equality_substitution) for p in SUBSTITUTABLE),
    Rule("equality_symmetry", "equals", None, foundations.equality_symmetry),
    Rule("disjunctive_syllogism_not_is", "or", "not_is", foundations.disjunctive_syllogism),
    Rule("disjunctive_syllogism_is", "or", "is", foundations.disjunctive_syllogism),
    Rule("de_morgan_and", "not_and", None, foundations.de_morgan_and),
    Rule("de_morgan_or", "not_or", None, foundations.de_morgan_or),
    Rule("double_negation", "not_not", None, foundations.double_negation),
    Rule("conditional_proof", "assumes", "derives", foundations.conditional_proof),
)
