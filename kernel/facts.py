from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from kernel.truth import TruthValue, revision


class Source(Enum):
    USER = "user"
    DEDUCED = "deduced"
    INFERRED = "inferred"
    LEARNED = "learned"


@dataclass(frozen=True)
class Fact:
    subject: str
    predicate: str
    object: str
    confidence: float = 1.0
    source: Source = Source.USER
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.subject or not self.predicate or not self.object:
            raise ValueError("subject, predicate, and object must be non-empty")
        if not self.subject.strip() or not self.predicate.strip() or not self.object.strip():
            raise ValueError("subject, predicate, and object must not be whitespace-only")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be 0.0-1.0, got {self.confidence}")

    def __str__(self) -> str:
        return f"{self.subject} {self.predicate} {self.object}"

    def negate(self) -> Fact:
        return Fact(
            subject=self.subject,
            predicate=f"not_{self.predicate}",
            object=self.object,
            confidence=1.0 - self.confidence,
            source=Source.INFERRED,
        )


@dataclass
class Belief:
    fact: Fact
    proof_chain: list[str] = field(default_factory=list)
    truth: TruthValue | None = None
    evidence: int = 1

    def __post_init__(self):
        if self.truth is None:
            self.truth = TruthValue(self.fact.confidence, 0.5)

    @property
    def confidence(self) -> float:
        return self.truth.strength

    def revise(self, confidence: float, proof: str | None = None) -> None:
        """Fold one independent derivation into this belief."""
        if proof:
            self.proof_chain.append(proof)
        combined = revision(self.truth, TruthValue(min(1.0, max(0.0, confidence)), 0.5))
        self.truth = combined
        self.evidence += 1
