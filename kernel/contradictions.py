"""Confidence-based contradiction resolution.

When new facts conflict with existing beliefs,
flag them and resolve based on confidence and specificity.
"""

from __future__ import annotations

from kernel.facts import Belief, Fact, Source


class ContradictionResolver:
    """Legacy confidence-based resolution, plus the engine's recorded conflicts.

    Since Stage 1.5 (#31) the engine records every conflict itself
    (InferenceEngine.conflicts(), kernel/conflicts.py); get_contradictions()
    reports those as (positive, negative) belief pairs. check() and its
    confidence * source score are kept for callers that use them directly.
    """

    def __init__(self, engine=None):
        self.contradictions: list[tuple[Belief, Belief]] = []
        self._engine = engine

    def check(self, new_belief: Belief, existing_beliefs: list[Belief]) -> Belief | None:
        """Check if new belief contradicts any existing belief."""
        for existing in existing_beliefs:
            if self._contradicts(new_belief.fact, existing.fact):
                self.contradictions.append((new_belief, existing))
                return self._resolve(new_belief, existing)
        return None

    def _contradicts(self, a: Fact, b: Fact) -> bool:
        """Check if two facts contradict each other."""
        if a.subject != b.subject or a.object != b.object:
            return False
        if a.predicate.startswith("not_") and b.predicate == a.predicate[4:]:
            return True
        if b.predicate.startswith("not_") and a.predicate == b.predicate[4:]:
            return True
        return False

    def _resolve(self, new_belief: Belief, existing: Belief) -> Belief:
        """Resolve contradiction based on confidence and source priority."""
        source_priority = {
            Source.USER: 4,
            Source.DEDUCED: 3,
            Source.LEARNED: 2,
            Source.INFERRED: 1,
        }

        new_score = new_belief.confidence * source_priority.get(new_belief.fact.source, 0)
        existing_score = existing.confidence * source_priority.get(existing.fact.source, 0)

        if new_score > existing_score:
            return new_belief
        return existing

    def get_contradictions(self) -> list[tuple[Belief, Belief]]:
        recorded = []
        if self._engine is not None:
            beliefs = self._engine.beliefs
            recorded = [(beliefs[c.positive], beliefs[c.negative]) for c in self._engine.conflicts()]
        return list(self.contradictions) + recorded
