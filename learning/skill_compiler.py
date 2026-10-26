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
from kernel.rules import Rule


@dataclass
class Skill:
    name: str
    domain: str
    premises: list[dict]
    conclusion: dict
    confidence: float
    usage_count: int = 0
    success_rate: float = 0.0
    successes: int = 0
    attempts: int = 0
    compiled_at: float = field(default_factory=time.time)
    source: str = "compiled"

    @property
    def fitness(self) -> float:
        """Skill confidence weighted by observed success; untested = confidence."""
        if self.attempts == 0:
            return self.confidence
        return self.confidence * (self.successes / self.attempts)

    def record_outcome(self, success: bool) -> None:
        self.attempts += 1
        self.usage_count += 1
        if success:
            self.successes += 1
        self.success_rate = self.successes / self.attempts

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Skill":
        return cls(**data)


def _bind(term: str, value: str, bindings: dict[str, str]) -> bool:
    """A term starting with `?` is a variable; anything else is literal."""
    if term.startswith("?"):
        if term in bindings:
            return bindings[term] == value
        bindings[term] = value
        return True
    return term == value


def _match(spec: dict, fact: Fact, bindings: dict[str, str]) -> bool:
    return (
        _bind(spec.get("subject", ""), fact.subject, bindings)
        and _bind(spec.get("predicate", ""), fact.predicate, bindings)
        and _bind(spec.get("object", ""), fact.object, bindings)
    )


def _ground(term: str, bindings: dict[str, str]) -> str:
    if term.startswith("?") and term in bindings:
        return bindings[term]
    return term


def skill_to_rule(skill: "Skill") -> Rule | None:
    """Compile a skill into an executable layer-2 inference rule.

    Terms beginning with `?` are variables, so a generalised skill fires on
    any matching facts, not just the trajectory it was learned from.

    chisel: pairwise matching only (<=2 premises); skills with more premises
    return None rather than inferring from a partial match. Upgrade to n-ary
    matching when n-ary atoms land.
    """
    premises = skill.premises
    if not premises or len(premises) > 2:
        return None
    trigger = premises[0].get("predicate", "")
    if not trigger or trigger.startswith("?"):
        return None

    def apply(fact: Fact, partner: Fact | None) -> Fact | None:
        bindings: dict[str, str] = {}
        if not _match(premises[0], fact, bindings):
            return None
        confidence = fact.confidence * skill.confidence
        if len(premises) == 2:
            if partner is None or not _match(premises[1], partner, bindings):
                return None
            confidence *= partner.confidence
        conclusion = skill.conclusion
        return Fact(
            subject=_ground(conclusion["subject"], bindings),
            predicate=conclusion["predicate"],
            object=_ground(conclusion["object"], bindings),
            confidence=min(1.0, confidence),
            source=Source.LEARNED,
        )

    partner_predicate = premises[1].get("predicate") if len(premises) == 2 else None
    if partner_predicate is not None and partner_predicate.startswith("?"):
        return None
    return Rule(f"skill:{skill.name}", trigger, partner_predicate, apply)


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

    def rules(self) -> list[Rule]:
        compiled = (skill_to_rule(skill) for skill in self.skills.values())
        return [rule for rule in compiled if rule is not None]

    def get_skill(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def get_skills_by_domain(self, domain: str) -> list[Skill]:
        return [s for s in self.skills.values() if s.domain == domain]

    def get_usable_skills(self, confidence: float) -> list[Skill]:
        if confidence >= self.min_confidence_for_override:
            return list(self.skills.values())
        if confidence >= self.min_confidence_for_use:
            return [s for s in self.skills.values() if s.fitness >= self.min_confidence_for_use]
        return []

    def should_use_skill(self, skill: Skill) -> bool:
        return skill.fitness >= self.min_confidence_for_use

    def should_override_with_skill(self, skill: Skill) -> bool:
        return skill.fitness >= self.min_confidence_for_override

    def record_outcome(self, name: str, success: bool) -> Skill | None:
        skill = self.skills.get(name)
        if skill is None:
            return None
        skill.record_outcome(success)
        self._save_skill(skill)
        return skill

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
