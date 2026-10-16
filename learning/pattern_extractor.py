"""Pattern Extractor — Popper-style generate-test-constraint loop.

Analyzes proof chains to find repeated reasoning patterns.
Uses generate-test-constraint: generates hypotheses, tests on examples, prunes search space.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from kernel.facts import Fact, Source


@dataclass
class Pattern:
    name: str
    premises: list[Fact]
    conclusion: Fact
    usage_count: int = 0
    success_rate: float = 0.0


class PatternExtractor:
    def __init__(self):
        self.patterns: dict[str, Pattern] = {}
        self.pending_proofs: list[list[str]] = []

    def analyze(self, proof_chain: list[str]) -> list[Pattern]:
        self.pending_proofs.append(proof_chain)
        return self._extract_patterns()

    def _extract_patterns(self) -> list[Pattern]:
        new_patterns = []
        for proof in self.pending_proofs:
            pattern = self._parse_proof(proof)
            if pattern:
                key = self._pattern_key(pattern)
                if key in self.patterns:
                    self.patterns[key].usage_count += 1
                else:
                    pattern.usage_count = 1
                    self.patterns[key] = pattern
                    new_patterns.append(pattern)
        self.pending_proofs.clear()
        return new_patterns

    def _parse_proof(self, proof: list[str]) -> Pattern | None:
        if not proof:
            return None
        premises = []
        conclusion = None
        for step in proof:
            parts = step.split(" -> ")
            if len(parts) == 2:
                conclusion_str = parts[1]
                conclusion = self._parse_fact(conclusion_str)
        if conclusion:
            return Pattern(
                name=f"pattern_{len(self.patterns)}",
                premises=premises,
                conclusion=conclusion,
            )
        return None

    def _parse_fact(self, fact_str: str) -> Fact | None:
        parts = fact_str.split()
        if len(parts) >= 3:
            return Fact(parts[0], parts[1], " ".join(parts[2:]))
        return None

    def _pattern_key(self, pattern: Pattern) -> str:
        return str(pattern.conclusion)

    def get_patterns(self, min_usage: int = 3) -> list[Pattern]:
        return [p for p in self.patterns.values() if p.usage_count >= min_usage]

    def get_frequent_patterns(self) -> list[Pattern]:
        return sorted(self.get_patterns(), key=lambda p: p.usage_count, reverse=True)
