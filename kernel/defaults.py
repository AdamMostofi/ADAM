"""Defeasible defaults: general rules that admit exceptions (Stage 1.5, #31).

DR5.2: the logic floor stays strict. Layer 1 rules (kernel/foundations.py)
are deductively sound and never defeated. Defaults live here instead:

* "C typically D": members of C are usually members of D ("bird typically
  flier").
* "C typically_not D": members of C are usually not members of D
  ("penguin typically_not flier").

A default conclusion is defeasible: kernel/conflicts.py withdraws it when a
strict fact, or a more specific default, says otherwise. Nothing is deleted;
the losing belief is kept and marked.
"""
from __future__ import annotations

from kernel.facts import Fact
from kernel.foundations import EXISTS, MEMBERSHIP, _deduced, is_reserved
from kernel.foundations import TRUE
from kernel.rules import KERNEL_RULES_VERSION, Rule

DEFAULT_PREDICATES = frozenset({"typically", "typically_not"})
NEGATED = {"instance_of": "not_instance_of", "is": "not_is"}


def _usable(c_d: Fact, x_in_c: Fact) -> bool:
    return (
        x_in_c.predicate in MEMBERSHIP
        and x_in_c.object == c_d.subject
        and c_d.subject != c_d.object
        and all(t != TRUE and not is_reserved(t) for t in (c_d.subject, c_d.object))
        and x_in_c.subject != EXISTS
        and not is_reserved(x_in_c.subject)
    )


def default_inheritance(c_typically_d: Fact, x_in_c: Fact) -> Fact | None:
    """x instance_of C and "C typically D" give x instance_of D, unless something defeats it."""
    if c_typically_d.predicate == "typically" and _usable(c_typically_d, x_in_c):
        return _deduced(x_in_c.subject, x_in_c.predicate, c_typically_d.object,
                        c_typically_d.confidence * x_in_c.confidence)
    return None


def default_exclusion(c_typically_not_d: Fact, x_in_c: Fact) -> Fact | None:
    """x instance_of C and "C typically_not D" give x not_instance_of D, unless something defeats it."""
    if c_typically_not_d.predicate == "typically_not" and _usable(c_typically_not_d, x_in_c):
        return _deduced(x_in_c.subject, NEGATED[x_in_c.predicate], c_typically_not_d.object,
                        c_typically_not_d.confidence * x_in_c.confidence)
    return None


DEFAULT_RULES: tuple[Rule, ...] = (
    Rule("default_inheritance", "typically", "instance_of", default_inheritance, KERNEL_RULES_VERSION),
    Rule("default_inheritance_ambiguous", "typically", "is", default_inheritance, KERNEL_RULES_VERSION),
    Rule("default_exclusion", "typically_not", "instance_of", default_exclusion, KERNEL_RULES_VERSION),
    Rule("default_exclusion_ambiguous", "typically_not", "is", default_exclusion, KERNEL_RULES_VERSION),
)
DEFAULT_RULE_NAMES = frozenset(r.name for r in DEFAULT_RULES)
