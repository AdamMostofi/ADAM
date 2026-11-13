"""Answer one goal by searching only the facts connected to it.

The forward engine (kernel.engine) saturates every consequence of everything
it holds. `prove()` answers a single question instead:

1. Find the facts connected to the goal: facts whose terms link to the goal's
   terms, directly or through other facts. Every Layer 1 rule combines premises
   that share a term, so a fact outside this group can never help.
2. Apply the same Layer 1 rules (kernel.rules.BUILTIN_RULES) to that group
   until nothing new appears or the bounds are reached.
3. If the goal appears, return its proof: every step with all its premises,
   in the order they were derived.

Because it uses the same rule functions as forward inference, prove() can't
disagree with it (tests/integration/test_prove_agreement.py checks this).
It never adds beliefs to the engine.

Bounds: `max_depth` limits how many rule applications deep a conclusion may
be; STEP_LIMIT caps the total rule applications per call.
"""

from __future__ import annotations

from kernel.facts import Fact
from kernel.foundations import (
    ARBITRARY_PREFIX, EXISTS, TRUE, canonical_fact, contradiction_detection, split_term,
)
from kernel.rules import BUILTIN_RULES

STEP_LIMIT = 200_000
_UNLINKED = {TRUE, EXISTS}


def _base(term: str) -> str:
    """Terms that rules treat as related share a base: "not:a" and "a"; "arbitrary_man" and "man"."""
    base, _ = split_term(term)
    if base.startswith(ARBITRARY_PREFIX) and len(base) > len(ARBITRARY_PREFIX):
        base = base[len(ARBITRARY_PREFIX):]
    return base


def _connected(facts: list[Fact], seeds: set[str]) -> list[Fact]:
    """Facts linked to the seed terms through shared terms (ignoring the reserved "true" and "exists")."""
    links: dict[str, list[int]] = {}
    for i, f in enumerate(facts):
        for term in {_base(f.subject), _base(f.object)} - _UNLINKED:
            links.setdefault(term, []).append(i)
    reached_terms, reached_facts = set(), set()
    frontier = [_base(t) for t in seeds if _base(t) not in _UNLINKED]
    while frontier:
        term = frontier.pop()
        if term in reached_terms:
            continue
        reached_terms.add(term)
        for i in links.get(term, []):
            if i not in reached_facts:
                reached_facts.add(i)
                f = facts[i]
                frontier.extend({_base(f.subject), _base(f.object)} - _UNLINKED - reached_terms)
    return [facts[i] for i in sorted(reached_facts)]


def _key(f: Fact) -> tuple[str, str, str]:
    return (f.subject, f.predicate, f.object)


def prove(engine, subject: str, predicate: str, object: str, max_depth: int = 6) -> list[str] | None:
    """Return the proof of (subject, predicate, object), or None if it can't be shown within the bounds."""
    goal_fact = canonical_fact(Fact(subject, predicate, object))
    subject, predicate, object = goal_fact.subject, goal_fact.predicate, goal_fact.object
    goal = (subject, predicate, object)
    facts = engine.strict_facts()  # defaults are not proofs (Stage 1.5)
    if goal in {_key(f) for f in facts}:
        return [f"[given] {subject} {predicate} {object}"]

    seeds = {subject, object} - _UNLINKED
    relevant = _connected(facts, seeds) if {_base(s) for s in seeds} - _UNLINKED else facts
    known: dict[tuple[str, str, str], Fact] = {_key(f): f for f in relevant}
    depth: dict[tuple[str, str, str], int] = {k: 0 for k in known}
    how: dict[tuple[str, str, str], tuple[str, tuple]] = {}
    steps = 0

    while goal not in known:
        by_predicate: dict[str, list[Fact]] = {}
        for f in known.values():
            by_predicate.setdefault(f.predicate, []).append(f)
        new: list[tuple[Fact, str, tuple]] = []
        for rule in BUILTIN_RULES:
            firsts = by_predicate.get(rule.trigger, [])
            combos = [(f,) for f in firsts] if rule.partner is None else \
                [(f, g) for f in firsts for g in by_predicate.get(rule.partner, [])]
            for args in combos:
                steps += 1
                if steps > STEP_LIMIT:
                    return None
                out = rule.apply(*args)
                for r in (out if isinstance(out, list) else [out] if out else []):
                    new.append((r, rule.name, args))
        for positive, negative in (("is", "not_is"), ("instance_of", "not_instance_of")):
            for f in by_predicate.get(positive, []):
                for g in by_predicate.get(negative, []):
                    c = contradiction_detection(f, g)
                    if c:
                        new.append((c, "contradiction_detection", (f, g)))
        added = False
        for fact, rule_name, args in new:
            k = _key(fact)
            d = 1 + max(depth[_key(a)] for a in args)
            if k in known or d > max_depth:
                continue
            known[k], depth[k], how[k] = fact, d, (rule_name, args)
            added = True
        if not added:
            return None
    return _explain(goal, how)


def _explain(goal, how) -> list[str]:
    """Proof steps for `goal`, premises first, each naming every premise."""
    ordered: list[str] = []
    done: set = set()

    def visit(k):
        if k in done:
            return
        done.add(k)
        if k not in how:
            ordered.append(f"[given] {' '.join(k)}")
            return
        rule_name, args = how[k]
        for a in args:
            visit(_key(a))
        premises = " + ".join(str(a) for a in args)
        ordered.append(f"[{rule_name}] {premises} -> {' '.join(k)}")

    visit(goal)
    return ordered
