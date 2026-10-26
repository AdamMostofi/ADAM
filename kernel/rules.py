"""Declarative inference rules.

Hyperon/MeTTa treats rules as data: a rule is just another atom, so learning
a rule and writing one are the same act. ADAM keeps its immutable Layer 1
rules in `kernel/foundations.py`, but exposes them here through one uniform
`Rule` table. The engine walks this table instead of hardcoding an if-chain,
and layer-2 learned rules (compiled skills) can be appended at runtime via
`InferenceEngine.add_rule`.

Layer 1 stays immutable: `BUILTIN_RULES` is fixed at import time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from kernel import foundations
from kernel.facts import Fact

RuleResult = Fact | list[Fact] | None
RuleFn = Callable[..., RuleResult]


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
    Rule("transitivity", "implies", "implies", foundations.transitivity),
    Rule("modus_tollens", "implies", "not_is", foundations.modus_tollens),
    Rule("existential_generalization", "is", None, foundations.existential_generalization),
    Rule("subtype_transitivity", "is", "implies", foundations.subtype_transitivity),
    Rule("is_transitivity", "is", "is", foundations.is_transitivity),
    Rule("universal_instantiation", "all_are", "is", foundations.universal_instantiation),
    Rule("universal_generalization", "all_are", None, foundations.universal_generalization),
    Rule("equality_substitution_is", "equals", "is", foundations.equality_substitution),
    Rule("equality_substitution_equals", "equals", "equals", foundations.equality_substitution),
    Rule("disjunctive_syllogism", "or", "not_is", foundations.disjunctive_syllogism),
    Rule("de_morgan_and", "not_and", None, foundations.de_morgan_and),
    Rule("de_morgan_or", "not_or", None, foundations.de_morgan_or),
    Rule("double_negation", "not_not", None, foundations.double_negation),
    Rule("conditional_proof", "assumes", "derives", foundations.conditional_proof),
)
