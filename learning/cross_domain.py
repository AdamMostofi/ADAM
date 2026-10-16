"""Cross-Domain Connection — Gentner's Structure Mapping Theory + ATLAS methodology.

Maps relational structures between concepts across different domains.
ADAM builds its own structural representations using embeddings + relational extraction.
"""
from __future__ import annotations

from dataclasses import dataclass

from kernel.facts import Fact


@dataclass
class Analogy:
    source_concept: str
    target_concept: str
    mapping: dict[str, str]
    confidence: float
    source: str = "automatic"


class CrossDomainMapper:
    def __init__(self, similarity_fn=None, similarity_threshold: float = 0.7):
        self.similarity_fn = similarity_fn
        self.similarity_threshold = similarity_threshold
        self.analogies: list[Analogy] = []
        self.manual_analogies: list[Analogy] = []

    def extract_structure(self, concept: str, facts: list[Fact]) -> list[tuple[str, str, str]]:
        structure = []
        for fact in facts:
            if fact.subject == concept:
                structure.append((fact.subject, fact.predicate, fact.object))
            elif fact.object == concept:
                structure.append((fact.object, fact.predicate, fact.subject))
        return structure

    def map_domains(self, source_concept: str, target_concept: str, source_facts: list[Fact], target_facts: list[Fact]) -> Analogy | None:
        source_structure = self.extract_structure(source_concept, source_facts)
        target_structure = self.extract_structure(target_concept, target_facts)
        if not source_structure or not target_structure:
            return None
        mapping = {}
        for s_subj, s_pred, s_obj in source_structure:
            for t_subj, t_pred, t_obj in target_structure:
                if s_pred == t_pred:
                    mapping[s_subj] = t_subj
                    mapping[s_obj] = t_obj
        if not mapping:
            if self.similarity_fn:
                try:
                    sim = self.similarity_fn(source_concept, target_concept)
                    if sim >= self.similarity_threshold:
                        mapping[source_concept] = target_concept
                except Exception:
                    pass
        if not mapping:
            return None
        confidence = min(1.0, len(mapping) / max(len(source_structure), 1))
        return Analogy(
            source_concept=source_concept,
            target_concept=target_concept,
            mapping=mapping,
            confidence=confidence,
        )

    def add_manual_analogy(self, source_concept: str, target_concept: str, mapping: dict[str, str]) -> Analogy:
        analogy = Analogy(
            source_concept=source_concept,
            target_concept=target_concept,
            mapping=mapping,
            confidence=1.0,
            source="manual",
        )
        self.manual_analogies.append(analogy)
        self.analogies.append(analogy)
        return analogy

    def get_analogies(self, concept: str) -> list[Analogy]:
        manual = [a for a in self.manual_analogies if a.source_concept == concept or a.target_concept == concept]
        auto = [a for a in self.analogies if a.source == "automatic" and (a.source_concept == concept or a.target_concept == concept)]
        return manual + auto

    def get_all_analogies(self) -> list[Analogy]:
        return self.manual_analogies + [a for a in self.analogies if a.source == "automatic"]
