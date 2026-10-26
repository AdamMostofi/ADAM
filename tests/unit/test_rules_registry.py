"""Layer-2 rules: a compiled skill must be executable by the engine."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.engine import InferenceEngine
from kernel.facts import Fact, Source
from kernel.rules import BUILTIN_RULES
from learning.skill_compiler import Skill, skill_to_rule


def _skill(name="mutual", premises=None, conclusion=None, confidence=0.9):
    return Skill(
        name=name,
        domain="social",
        premises=premises or [
            {"subject": "?x", "predicate": "likes", "object": "?y"},
            {"subject": "?y", "predicate": "likes", "object": "?x"},
        ],
        conclusion=conclusion or {"subject": "?x", "predicate": "friends", "object": "?y"},
        confidence=confidence,
    )


def test_builtin_rules_cover_all_layer1_rules():
    names = {rule.name for rule in BUILTIN_RULES}
    assert "modus_ponens" in names
    assert "transitivity" in names
    assert "contradiction_detection" not in names


def test_learned_skill_runs_as_rule():
    engine = InferenceEngine()
    rule = skill_to_rule(_skill())
    assert rule is not None
    engine.add_rule(rule)
    engine.add_facts([Fact("ann", "likes", "bob"), Fact("bob", "likes", "ann")])
    engine.infer()
    hits = engine.query("ann", "friends", "bob")
    assert hits and hits[0].fact.source == Source.LEARNED
    assert abs(hits[0].confidence - 0.9) < 1e-9


def test_rule_requires_both_premises():
    engine = InferenceEngine()
    engine.add_rule(skill_to_rule(_skill()))
    engine.add_facts([Fact("ann", "likes", "bob")])
    engine.infer()
    assert engine.query("ann", "friends", "bob") == []


def test_add_rule_is_idempotent():
    engine = InferenceEngine()
    rule = skill_to_rule(_skill())
    engine.add_rule(rule)
    engine.add_rule(rule)
    assert len([r for r in engine.rules if r.name == rule.name]) == 1


def test_three_premise_skill_not_compiled():
    skill = _skill(premises=[
        {"subject": "a", "predicate": "p", "object": "b"},
        {"subject": "b", "predicate": "p", "object": "c"},
        {"subject": "c", "predicate": "p", "object": "d"},
    ])
    assert skill_to_rule(skill) is None
