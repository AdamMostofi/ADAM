"""Unification: pattern matching between facts.

Does B in fact 1 equal B in fact 2? If yes, link them.
This is what lets A>B and B>C connect.
"""

from __future__ import annotations

from kernel.facts import Fact


def unify(fact_a: Fact, fact_b: Fact) -> dict[str, str] | None:
    """Attempt to unify two facts. Returns variable bindings or None."""
    bindings: dict[str, str] = {}

    if not _unify_term(fact_a.subject, fact_b.subject, bindings):
        return None
    if not _unify_term(fact_a.predicate, fact_b.predicate, bindings):
        return None
    if not _unify_term(fact_a.object, fact_b.object, bindings):
        return None

    return bindings


def _unify_term(a: str, b: str, bindings: dict[str, str]) -> bool:
    """Unify two terms, updating bindings. Includes occurs check."""
    if a == b:
        return True
    if a.startswith("?"):
        if a in bindings:
            return bindings[a] == b
        if _occurs_check(a, b, bindings):
            return False
        bindings[a] = b
        return True
    if b.startswith("?"):
        if b in bindings:
            return bindings[b] == a
        if _occurs_check(b, a, bindings):
            return False
        bindings[b] = a
        return True
    return False


def _occurs_check(var: str, term: str, bindings: dict[str, str]) -> bool:
    """Prevent circular bindings: var must not occur in term."""
    if var == term:
        return True
    if term in bindings:
        return _occurs_check(var, bindings[term], bindings)
    return False


def find_unifiable(fact: Fact, facts: list[Fact]) -> list[tuple[Fact, dict[str, str]]]:
    """Find all facts that unify with the given fact."""
    results = []
    for other in facts:
        bindings = unify(fact, other)
        if bindings is not None:
            results.append((other, bindings))
    return results
