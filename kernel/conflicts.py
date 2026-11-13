"""Contradictions as state, and how defaults lose to better evidence (Stage 1.5, #31).

DR5.1: a contradiction is state, not failure. After inference, `analyse()`
looks at every pair of beliefs that contradict each other (x instance_of C
with x not_instance_of C, or the same with an ambiguous "is") and records a
Conflict. How it ends depends on what supports each side:

* Both strict (given, or derived only by Layer 1 rules): nothing is
  withdrawn; the conflict is recorded for review ("unresolved").
* One strict, one resting on a default: the default side is defeated
  ("strict_beats_default"). Specific evidence about the individual is a
  strict fact, so "pingu not_instance_of flier" beats "bird typically flier".
* Both from defaults: the default about the more specific class wins
  ("more_specific_default"): "penguin typically_not flier" beats "bird
  typically flier" when penguin is a (strict) subclass of bird. If neither
  class is more specific (the Nixon diamond), both sides are withheld
  ("contested").

Nothing is deleted. Each belief gets a status:

* active: holds;
* defeated: lost a conflict;
* contested: withheld because the defaults disagree with no winner;
* unsupported: every derivation rests on a belief that is not active.

Statuses are a function of the beliefs alone, so they don't depend on the
order facts arrived in. Removing the evidence that defeated a default
restores the default's conclusion.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from kernel.defaults import DEFAULT_PREDICATES, DEFAULT_RULE_NAMES
from kernel.facts import Derivation

Key = tuple[str, str, str]
POSITIVE = {"is": "not_is", "instance_of": "not_instance_of"}

ACTIVE, DEFEATED, CONTESTED, UNSUPPORTED = "active", "defeated", "contested", "unsupported"


@dataclass(frozen=True)
class Conflict:
    """Two beliefs that can't both hold, with everything needed to review them."""

    positive: Key
    negative: Key
    kind: str                    # "strict" (both strict) or "defeasible" (a default is involved)
    resolution: str              # unresolved | strict_beats_default | more_specific_default | contested
    winner: Key | None
    positive_sources: tuple[str, ...]
    negative_sources: tuple[str, ...]
    positive_proofs: tuple[Derivation, ...] = field(default_factory=tuple)
    negative_proofs: tuple[Derivation, ...] = field(default_factory=tuple)

    @property
    def loser(self) -> Key | None:
        if self.winner is None:
            return None
        return self.negative if self.winner == self.positive else self.positive

    def to_record(self) -> dict:
        return {
            "positive": list(self.positive), "negative": list(self.negative), "kind": self.kind,
            "resolution": self.resolution, "winner": list(self.winner) if self.winner else None,
            "positive_sources": list(self.positive_sources), "negative_sources": list(self.negative_sources),
            "positive_proofs": [d.to_record(self.positive) for d in self.positive_proofs],
            "negative_proofs": [d.to_record(self.negative) for d in self.negative_proofs],
        }


def _grounded(beliefs, allowed, blocked=frozenset()) -> set[Key]:
    """Least fixpoint: given beliefs, plus beliefs with an allowed derivation whose premises are all in."""
    good = {k for k, b in beliefs.items() if b.given and k not in blocked}
    pending = {k for k in beliefs if k not in good and k not in blocked}
    changed = True
    while changed:
        changed = False
        for k in list(pending):
            if any(allowed(d) and all(p in good for p in d.premises) for d in beliefs[k].proofs):
                good.add(k)
                pending.discard(k)
                changed = True
    return good


def _default_classes(belief) -> set[str]:
    """The classes whose defaults directly gave this belief."""
    return {p[0] for d in belief.proofs if d.rule in DEFAULT_RULE_NAMES
            for p in d.premises if p[1] in DEFAULT_PREDICATES}


def analyse(engine) -> tuple[dict[Key, str], list[Conflict]]:
    """Statuses for beliefs that are not simply active, and every conflict, sorted."""
    beliefs = engine.beliefs
    pairs = sorted(
        ((s, p, o), (s, n, o))
        for p, n in POSITIVE.items()
        for (s, _, o) in engine.index.get(p, ())
        if (s, n, o) in beliefs
    )
    has_defaults = any(engine.index.get(p) for p in DEFAULT_PREDICATES)
    if not pairs:
        return {}, []
    strict = _grounded(beliefs, lambda d: d.rule not in DEFAULT_RULE_NAMES) if has_defaults else set(beliefs)

    def more_specific(a: str, b: str) -> bool:
        return a != b and ((a, "subclass_of", b) in strict or (a, "implies", b) in strict)

    defeated: set[Key] = set()
    contested: set[Key] = set()
    conflicts: list[Conflict] = []
    for pos, neg in pairs:
        pos_strict, neg_strict = pos in strict, neg in strict
        winner = None
        if pos_strict and neg_strict:
            kind, resolution = "strict", "unresolved"
        elif pos_strict or neg_strict:
            kind, resolution = "defeasible", "strict_beats_default"
            winner = pos if pos_strict else neg
        else:
            kind = "defeasible"
            pos_classes, neg_classes = _default_classes(beliefs[pos]), _default_classes(beliefs[neg])
            neg_wins = any(more_specific(a, b) for a in neg_classes for b in pos_classes)
            pos_wins = any(more_specific(a, b) for a in pos_classes for b in neg_classes)
            if neg_wins != pos_wins:
                resolution, winner = "more_specific_default", (neg if neg_wins else pos)
            else:
                resolution = "contested"
        if winner is not None:
            defeated.add(neg if winner == pos else pos)
        elif resolution == "contested":
            contested.update((pos, neg))
        conflicts.append(Conflict(
            pos, neg, kind, resolution, winner,
            tuple(engine.attribution(*pos)), tuple(engine.attribution(*neg)),
            tuple(beliefs[pos].proofs), tuple(beliefs[neg].proofs),
        ))

    withheld = defeated | contested
    if not withheld:
        return {}, conflicts
    active = _grounded(beliefs, lambda d: True, blocked=frozenset(withheld))
    statuses = {}
    for k in beliefs:
        if k in active:
            continue
        statuses[k] = DEFEATED if k in defeated else CONTESTED if k in contested else UNSUPPORTED
    return statuses, conflicts
