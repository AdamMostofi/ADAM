"""Goal-directed backward chaining.

The forward engine (kernel.engine) saturates every consequence of its
agenda. That is cheap at small scale but it means a query pays for
deductions it never asked about. This module searches backward from a goal
instead, the way PLN and NARS answer a question: start at what you want to
prove, work down to what you already believe.

Supported goals:
    (s, "is", o)       -- direct, modus ponens, is-transitivity, all_are
    (s, "implies", o)  -- direct, implications transitivity

`X is X` is treated as axiomatic, so a bare implication is enough to satisfy
a self-referential goal.
"""

from __future__ import annotations

STEP_LIMIT = 2000


def prove(engine, subject: str, predicate: str, object: str, max_depth: int = 6) -> list[str] | None:
    """Return an ordered proof chain for the goal, or None if unprovable."""
    state = {"steps": 0}
    return _prove(engine, subject, predicate, object, max_depth, set(), state)


def _direct(engine, subject: str, predicate: str, object: str) -> bool:
    return any(
        b.fact.subject == subject and b.fact.predicate == predicate and b.fact.object == object
        for b in engine.beliefs.values()
    )


def _prove(engine, s: str, p: str, o: str, depth: int, seen: set, state) -> list[str] | None:
    if depth <= 0 or state["steps"] >= STEP_LIMIT:
        return None
    goal = (s, p, o)
    if goal in seen:
        return None
    state["steps"] += 1

    if _direct(engine, s, p, o):
        return [f"[given] {s} {p} {o}"]

    if p == "is":
        if s == o:
            return [f"[axiom] {s} is {s}"]

        # modus ponens: (s implies m) + prove(m is o)
        for belief in list(engine.beliefs.values()):
            f = belief.fact
            if f.predicate != "implies" or f.subject != s:
                continue
            if f.object == o:
                return [f"[modus_ponens] {s} implies {o} + {s} is {s}"]
            sub = _prove(engine, f.object, "is", o, depth - 1, seen | {goal}, state)
            if sub is not None:
                return [f"[modus_ponens] {s} implies {f.object}"] + sub

        # is-transitivity: (s is m) + prove(m is o)
        for belief in list(engine.beliefs.values()):
            f = belief.fact
            if f.predicate != "is" or f.subject != s or f.object == s:
                continue
            sub = _prove(engine, f.object, "is", o, depth - 1, seen | {goal}, state)
            if sub is not None:
                return [f"[is_transitivity] {s} is {f.object}"] + sub

        # universal instantiation: (s is m) + (m all_are o)
        for belief in list(engine.beliefs.values()):
            f = belief.fact
            if f.predicate != "all_are" or f.object != o:
                continue
            if _direct(engine, s, "is", f.subject):
                return [f"[universal_instantiation] {s} is {f.subject} + {f.subject} all_are {o}"]

    if p == "implies":
        # transitivity: (s implies m) + prove(m implies o)
        for belief in list(engine.beliefs.values()):
            f = belief.fact
            if f.predicate != "implies" or f.subject != s or f.object == o:
                continue
            sub = _prove(engine, f.object, "implies", o, depth - 1, seen | {goal}, state)
            if sub is not None:
                return [f"[transitivity] {s} implies {f.object}"] + sub

    return None
