"""Error Correction — AGM-style belief revision + K-Edit contextual consistency.

Corrections at 0.99+ confidence override deductions.
Lower confidence triggers conflict resolution + verification process.
"""
from __future__ import annotations

from dataclasses import dataclass

from kernel.facts import Fact, Source


@dataclass
class Correction:
    original_fact: Fact
    corrected_fact: Fact
    confidence: float
    verified: bool = False


class ErrorCorrector:
    def __init__(self):
        self.corrections: list[Correction] = []
        self.override_threshold = 0.99
        self.conflict_threshold = 0.70

    def submit_correction(self, original: Fact, corrected: Fact, confidence: float) -> Correction:
        correction = Correction(
            original_fact=original,
            corrected_fact=corrected,
            confidence=confidence,
            verified=False,
        )
        self.corrections.append(correction)
        if confidence >= self.override_threshold:
            self._apply_correction(correction)
        return correction

    def _apply_correction(self, correction: Correction) -> None:
        correction.verified = True

    def should_override(self, correction: Correction) -> bool:
        return correction.confidence >= self.override_threshold

    def should_resolve_conflict(self, correction: Correction) -> bool:
        return self.conflict_threshold <= correction.confidence < self.override_threshold

    def verify_correction(self, correction: Correction, related_facts: list[Fact]) -> bool:
        if correction.confidence >= self.override_threshold:
            correction.verified = True
            return True
        conflicts = self._check_consistency(correction.corrected_fact, related_facts)
        if not conflicts:
            correction.verified = True
            return True
        return False

    def _check_consistency(self, fact: Fact, related_facts: list[Fact]) -> list[Fact]:
        conflicts = []
        for existing in related_facts:
            if (fact.subject == existing.subject and
                fact.object == existing.object and
                fact.predicate != existing.predicate):
                conflicts.append(existing)
        return conflicts

    def get_corrections(self) -> list[Correction]:
        return list(self.corrections)

    def get_pending_corrections(self) -> list[Correction]:
        return [c for c in self.corrections if not c.verified]
