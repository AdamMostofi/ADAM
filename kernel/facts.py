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


Key = tuple[str, str, str]


@dataclass(frozen=True)
class Derivation:
    """One way a belief was derived (Stage 1.4, #30): the record is the truth, text is a rendering.

    `premises` are the (subject, predicate, object) keys of the facts the rule
    combined, in the order the rule took them. `confidence` is what this
    derivation gives, using the best confidence of each premise.
    """

    rule: str
    premises: tuple[Key, ...]
    confidence: float
    rule_version: str = "1"

    @property
    def identity(self) -> tuple[str, frozenset]:
        """Same rule and same premise set: the same derivation, whatever the order."""
        return (self.rule, tuple(sorted(self.premises)))

    def render(self, conclusion: Key) -> str:
        premises = " + ".join(" ".join(p) for p in self.premises)
        return f"[{self.rule}] {premises} -> {' '.join(conclusion)}"

    def to_record(self, conclusion: Key) -> dict:
        """Plain data, for storage and for the thought trace's INFER steps (#35)."""
        return {"conclusion": list(conclusion), "rule": self.rule, "rule_version": self.rule_version,
                "premises": [list(p) for p in self.premises], "confidence": self.confidence}


@dataclass
class Belief:
    fact: Fact
    # Text notes added outside the engine (Belief.revise); derivations are rendered from `proofs`.
    notes: list[str] = field(default_factory=list)
    truth: TruthValue | None = None
    evidence: int = 1
    # True when the fact was given (by the user, memory or learning) rather than only derived.
    given: bool = True
    # The highest confidence it was given with (derivations may raise `confidence` above it).
    given_confidence: float | None = None
    # Distinct derivation identities (rule, premise set) -> index of their record in `proofs`.
    derivations: dict = field(default_factory=dict)
    # The derivation records, in the order they were found (the first is the founding one).
    proofs: list = field(default_factory=list)

    def __post_init__(self):
        if self.truth is None:
            self.truth = TruthValue(self.fact.confidence, 0.5)
        if self.given and self.given_confidence is None:
            self.given_confidence = self.fact.confidence

    @property
    def confidence(self) -> float:
        """The best support for this belief: its most confident derivation, or its highest given value.

        This is the confidence every API exposes (Stage 1.2, #28; defined in Stage 1.4, #30).
        `evidence` counts distinct derivations separately.
        """
        return self.truth.strength

    @property
    def proof_chain(self) -> list[str]:
        """Readable proofs, rendered from the derivation records (DR4.1: the record is the truth)."""
        key = (self.fact.subject, self.fact.predicate, self.fact.object)
        return [proof.render(key) for proof in self.proofs] + list(self.notes)

    def revise(self, confidence: float, proof: str | None = None) -> None:
        """Fold one independent derivation into this belief."""
        if proof:
            self.notes.append(proof)
        combined = revision(self.truth, TruthValue(min(1.0, max(0.0, confidence)), 0.5))
        self.truth = combined
        self.evidence += 1
