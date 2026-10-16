"""Skill Compiler — HERAKLES-style trajectory distillation.

Compiles successful multi-step patterns into single reusable skills.
Skills stored as JSON files in dedicated directory for portability.
"""
from __future__ import annotations

import json
import os
import time
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

from kernel.facts import Fact, Source


@dataclass
class Skill:
    name: str
    domain: str
    premises: list[dict]
    conclusion: dict
    confidence: float
    usage_count: int = 0
    success_rate: float = 0.0
    compiled_at: float = field(default_factory=time.time)
    source: str = "compiled"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Skill":
        return cls(**data)


class SkillCompiler:
    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)
        self.skills: dict[str, Skill] = {}
        self.min_confidence_for_use = 0.70
        self.min_confidence_for_override = 0.99
        self._load_skills()

    def _load_skills(self) -> None:
        if not self.skills_dir.exists():
            return
        for json_file in self.skills_dir.rglob("*.json"):
            try:
                with open(json_file) as f:
                    data = json.load(f)
                skill = Skill.from_dict(data)
                self.skills[skill.name] = skill
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

    def compile_skill(self, name: str, domain: str, premises: list[Fact], conclusion: Fact, confidence: float) -> Skill:
        skill = Skill(
            name=name,
            domain=domain,
            premises=[{"subject": p.subject, "predicate": p.predicate, "object": p.object} for p in premises],
            conclusion={"subject": conclusion.subject, "predicate": conclusion.predicate, "object": conclusion.object},
            confidence=confidence,
        )
        self.skills[name] = skill
        self._save_skill(skill)
        return skill

    def _save_skill(self, skill: Skill) -> None:
        domain_dir = self.skills_dir / skill.domain
        domain_dir.mkdir(parents=True, exist_ok=True)
        with open(domain_dir / f"{skill.name}.json", "w") as f:
            json.dump(skill.to_dict(), f, indent=2)

    def get_skill(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def get_skills_by_domain(self, domain: str) -> list[Skill]:
        return [s for s in self.skills.values() if s.domain == domain]

    def get_usable_skills(self, confidence: float) -> list[Skill]:
        if confidence >= self.min_confidence_for_override:
            return list(self.skills.values())
        if confidence >= self.min_confidence_for_use:
            return [s for s in self.skills.values() if s.confidence >= self.min_confidence_for_use]
        return []

    def should_use_skill(self, skill: Skill) -> bool:
        return skill.confidence >= self.min_confidence_for_use

    def should_override_with_skill(self, skill: Skill) -> bool:
        return skill.confidence >= self.min_confidence_for_override

    def export_skills(self, zip_path: str) -> None:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for json_file in self.skills_dir.rglob("*.json"):
                zf.write(json_file, json_file.relative_to(self.skills_dir))

    def import_skills(self, zip_path: str) -> int:
        count = 0
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                if member.endswith(".json"):
                    with zf.open(member) as f:
                        data = json.load(f)
                    skill = Skill.from_dict(data)
                    self.skills[skill.name] = skill
                    self._save_skill(skill)
                    count += 1
        return count
