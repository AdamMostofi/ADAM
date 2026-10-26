"""LearningEngine — main API for continuous learning.

Wraps pattern extraction, skill compilation, cross-domain mapping, and error correction.
"""
from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine
from learning.pattern_extractor import PatternExtractor
from learning.skill_compiler import SkillCompiler, skill_to_rule
from learning.cross_domain import CrossDomainMapper
from learning.error_correction import ErrorCorrector


class LearningEngine:
    def __init__(self, skills_dir: str = "skills", memory_system=None):
        self.pattern_extractor = PatternExtractor()
        self.skill_compiler = SkillCompiler(skills_dir)
        self.cross_domain = CrossDomainMapper()
        self.error_corrector = ErrorCorrector()
        self.engine = InferenceEngine()
        self.memory = memory_system
        self.skills_dir = Path(skills_dir)

    def learn_from_proof(self, proof_chain: list[str]) -> list:
        return self.pattern_extractor.analyze(proof_chain)

    def compile_skill(self, name: str, domain: str, premises: list[Fact], conclusion: Fact, confidence: float):
        skill = self.skill_compiler.compile_skill(name, domain, premises, conclusion, confidence)
        self._register_rule(skill)
        return skill

    def _register_rule(self, skill) -> None:
        if self.memory is None:
            return
        rule = skill_to_rule(skill)
        if rule is not None:
            self.memory.engine.add_rule(rule)

    def get_skill(self, name: str):
        return self.skill_compiler.get_skill(name)

    def get_usable_skills(self, confidence: float):
        return self.skill_compiler.get_usable_skills(confidence)

    def should_use_skill(self, skill) -> bool:
        return self.skill_compiler.should_use_skill(skill)

    def should_override_with_skill(self, skill) -> bool:
        return self.skill_compiler.should_override_with_skill(skill)

    def map_domains(self, source_concept: str, target_concept: str, source_facts: list[Fact], target_facts: list[Fact]):
        analogy = self.cross_domain.map_domains(source_concept, target_concept, source_facts, target_facts)
        if analogy:
            self.cross_domain.analogies.append(analogy)
        return analogy

    def add_manual_analogy(self, source_concept: str, target_concept: str, mapping: dict[str, str]):
        return self.cross_domain.add_manual_analogy(source_concept, target_concept, mapping)

    def get_analogies(self, concept: str):
        return self.cross_domain.get_analogies(concept)

    def record_skill_outcome(self, name: str, success: bool):
        return self.skill_compiler.record_outcome(name, success)

    def submit_correction(self, original: Fact, corrected: Fact, confidence: float):
        self._penalise_skills_claiming(original)
        correction = self.error_corrector.submit_correction(original, corrected, confidence)
        if confidence >= 0.99:
            self.engine.retract(original)
            self.engine.add_fact(corrected)
            self.engine.infer()
        return correction

    def _penalise_skills_claiming(self, fact: Fact) -> None:
        for skill in list(self.skill_compiler.skills.values()):
            conclusion = skill.conclusion
            if (
                conclusion.get("subject") == fact.subject
                and conclusion.get("predicate") == fact.predicate
                and conclusion.get("object") == fact.object
            ):
                self.skill_compiler.record_outcome(skill.name, False)

    def should_override_correction(self, correction) -> bool:
        return self.error_corrector.should_override(correction)

    def should_resolve_conflict(self, correction) -> bool:
        return self.error_corrector.should_resolve_conflict(correction)

    def verify_correction(self, correction, related_facts: list[Fact]):
        return self.error_corrector.verify_correction(correction, related_facts)

    def export_skills(self, zip_path: str) -> None:
        self.skill_compiler.export_skills(zip_path)

    def import_skills(self, zip_path: str) -> int:
        count = self.skill_compiler.import_skills(zip_path)
        for skill in self.skill_compiler.skills.values():
            self._register_rule(skill)
        return count

    def deep_learn(self) -> list:
        return self.pattern_extractor.get_frequent_patterns()
