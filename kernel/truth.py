"""PLN-style truth values and evidence revision.

ADAM's `Fact.confidence` is a single scalar: it mixes "how likely is this"
(strength) with "how much evidence supports it" (confidence). OpenCog's PLN
separates the two, and revision combines independent evidence properly:

    w_i = c_i / (1 - c_i)
    strength = sum(w_i * s_i) / sum(w_i)
    confidence = sum(w_i) / (sum(w_i) + 1)

Only revision is implemented here because it is the one operation the engine
currently needs: folding a second independent derivation into an existing
belief. Rule outputs still use multiplicative confidence (unchanged), so
single-pass behaviour is identical.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TruthValue:
    strength: float
    confidence: float

    def __post_init__(self):
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"strength must be 0.0-1.0, got {self.strength}")
        if not 0.0 <= self.confidence < 1.0:
            raise ValueError(f"confidence must be 0.0-<1.0, got {self.confidence}")

    @property
    def weight(self) -> float:
        return self.confidence / (1.0 - self.confidence)


def revision(a: TruthValue, b: TruthValue) -> TruthValue:
    """Combine two independent truth values for the same statement."""
    wa, wb = a.weight, b.weight
    total = wa + wb
    strength = (wa * a.strength + wb * b.strength) / total
    confidence = total / (total + 1.0)
    return TruthValue(min(1.0, max(0.0, strength)), min(0.999999, confidence))
