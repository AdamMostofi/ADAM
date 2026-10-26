"""MOSES-inspired adaptation: skills carry observed fitness, not just confidence."""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact
from learning.engine import LearningEngine
from learning.skill_compiler import Skill, SkillCompiler


def test_untested_skill_fitness_equals_confidence():
    skill = Skill(name="s", domain="d", premises=[], conclusion={}, confidence=0.95)
    assert skill.fitness == 0.95
    assert SkillCompiler().should_use_skill(skill)


def test_failures_reduce_fitness_and_disable_skill():
    skill = Skill(name="s", domain="d", premises=[], conclusion={}, confidence=0.95)
    skill.record_outcome(False)
    assert skill.attempts == 1
    assert skill.successes == 0
    assert skill.fitness == 0.0
    assert not SkillCompiler().should_use_skill(skill)


def test_mixed_outcomes_average():
    skill = Skill(name="s", domain="d", premises=[], conclusion={}, confidence=1.0)
    for ok in (True, True, False, True):
        skill.record_outcome(ok)
    assert abs(skill.fitness - 0.75) < 1e-9


def test_outcome_persists_to_disk():
    with tempfile.TemporaryDirectory() as tmp:
        compiler = SkillCompiler(skills_dir=tmp)
        compiler.compile_skill(
            "mutual", "social",
            [Fact("ann", "likes", "bob"), Fact("bob", "likes", "ann")],
            Fact("ann", "friends", "bob"), 0.95,
        )
        compiler.record_outcome("mutual", False)

        reloaded = SkillCompiler(skills_dir=tmp)
        skill = reloaded.get_skill("mutual")
        assert skill.attempts == 1
        assert skill.successes == 0
        assert skill.fitness == 0.0


def test_correction_penalises_skill_claiming_the_fact():
    with tempfile.TemporaryDirectory() as tmp:
        engine = LearningEngine(skills_dir=tmp)
        engine.compile_skill(
            "mutual", "social",
            [Fact("ann", "likes", "bob"), Fact("bob", "likes", "ann")],
            Fact("ann", "friends", "bob"), 0.95,
        )
        skill = engine.get_skill("mutual")
        assert skill.attempts == 0

        engine.submit_correction(Fact("ann", "friends", "bob"), Fact("ann", "friends", "ann"), 0.99)
        assert skill.attempts == 1
        assert skill.fitness == 0.0
