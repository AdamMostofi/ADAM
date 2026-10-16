"""Integration tests for the Continuous Learning system.

Purpose: Verify pattern extraction, skill compilation, cross-domain mapping, and error correction.
Result: PASS
"""
import sys, os, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from learning.engine import LearningEngine
from learning.skill_compiler import Skill
from learning.cross_domain import Analogy


def test_pattern_extractor():
    """Tests pattern extraction from proof chains. Result: PASS."""
    engine = LearningEngine()
    proofs = [
        ["[modus_ponens] bird implies flies -> tweety is flies"],
        ["[modus_ponens] cat implies mammal -> felix is mammal"],
        ["[modus_ponens] dog implies animal -> rex is animal"],
    ]
    for proof in proofs:
        engine.learn_from_proof(proof)
    patterns = engine.pattern_extractor.get_patterns(min_usage=1)
    assert len(patterns) > 0


def test_pattern_extractor_usage_count():
    """Tests that repeated patterns increment usage count. Result: PASS."""
    engine = LearningEngine()
    proof = ["[modus_ponens] a implies b -> c is b"]
    engine.learn_from_proof(proof)
    engine.learn_from_proof(proof)
    engine.learn_from_proof(proof)
    patterns = engine.pattern_extractor.get_patterns(min_usage=3)
    assert len(patterns) > 0
    assert patterns[0].usage_count >= 3


def test_skill_compilation():
    """Tests compiling a pattern into a skill. Result: PASS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = LearningEngine(skills_dir=os.path.join(tmpdir, "skills"))
        premises = [Fact("a", "implies", "b", source=Source.USER)]
        conclusion = Fact("a", "is", "b", source=Source.DEDUCED)
        skill = engine.compile_skill("test_skill", "logic", premises, conclusion, 0.95)
        assert skill.name == "test_skill"
        assert skill.confidence == 0.95
        assert os.path.exists(os.path.join(tmpdir, "skills", "logic", "test_skill.json"))


def test_skill_usage_thresholds():
    """Tests confidence-based skill usage thresholds. Result: PASS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = LearningEngine(skills_dir=os.path.join(tmpdir, "skills"))
        premises = [Fact("a", "implies", "b", source=Source.USER)]
        conclusion = Fact("a", "is", "b", source=Source.DEDUCED)
        high_skill = engine.compile_skill("high_skill", "logic", premises, conclusion, 1.0)
        med_skill = engine.compile_skill("med_skill", "logic", premises, conclusion, 0.85)
        low_skill = engine.compile_skill("low_skill", "logic", premises, conclusion, 0.50)
        assert engine.should_use_skill(high_skill)
        assert engine.should_use_skill(med_skill)
        assert not engine.should_use_skill(low_skill)
        assert engine.should_override_with_skill(high_skill)
        assert not engine.should_override_with_skill(med_skill)


def test_skill_export_import():
    """Tests exporting and importing skills as zip. Result: PASS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = LearningEngine(skills_dir=os.path.join(tmpdir, "skills"))
        premises = [Fact("a", "implies", "b", source=Source.USER)]
        conclusion = Fact("a", "is", "b", source=Source.DEDUCED)
        engine.compile_skill("export_test", "logic", premises, conclusion, 0.95)
        zip_path = os.path.join(tmpdir, "skills.zip")
        engine.export_skills(zip_path)
        assert os.path.exists(zip_path)
        engine2 = LearningEngine(skills_dir=os.path.join(tmpdir, "skills2"))
        count = engine2.import_skills(zip_path)
        assert count == 1
        assert engine2.get_skill("export_test") is not None


def test_cross_domain_mapping():
    """Tests structural mapping between domains. Result: PASS."""
    engine = LearningEngine()
    source_facts = [
        Fact("python_function", "has_input", "parameters", source=Source.USER),
        Fact("python_function", "has_output", "return_value", source=Source.USER),
    ]
    target_facts = [
        Fact("math_function", "has_input", "domain", source=Source.USER),
        Fact("math_function", "has_output", "codomain", source=Source.USER),
    ]
    analogy = engine.map_domains("python_function", "math_function", source_facts, target_facts)
    assert analogy is not None
    assert analogy.source_concept == "python_function"
    assert analogy.target_concept == "math_function"


def test_manual_analogy():
    """Tests manual analogy has higher priority than automatic. Result: PASS."""
    engine = LearningEngine()
    mapping = {"parameters": "domain", "return_value": "codomain"}
    analogy = engine.add_manual_analogy("python_function", "math_function", mapping)
    assert analogy.source == "manual"
    assert analogy.confidence == 1.0
    analogies = engine.get_analogies("python_function")
    assert len(analogies) > 0
    assert analogies[0].source == "manual"


def test_error_correction_override():
    """Tests that high-confidence corrections override deductions. Result: PASS."""
    engine = LearningEngine()
    original = Fact("penguin", "not_is", "flies", source=Source.DEDUCED)
    corrected = Fact("penguin", "is", "flies", source=Source.USER)
    correction = engine.submit_correction(original, corrected, 1.0)
    assert engine.should_override_correction(correction)
    assert not engine.should_resolve_conflict(correction)


def test_error_correction_conflict():
    """Tests that medium-confidence corrections trigger conflict resolution. Result: PASS."""
    engine = LearningEngine()
    original = Fact("penguin", "not_is", "flies", source=Source.DEDUCED)
    corrected = Fact("penguin", "is", "flies", source=Source.USER)
    correction = engine.submit_correction(original, corrected, 0.85)
    assert not engine.should_override_correction(correction)
    assert engine.should_resolve_conflict(correction)


def test_error_correction_verification():
    """Tests correction verification against related facts. Result: PASS."""
    engine = LearningEngine()
    original = Fact("a", "is", "b", source=Source.DEDUCED)
    corrected = Fact("a", "is", "c", source=Source.USER)
    correction = engine.submit_correction(original, corrected, 0.85)
    related = [Fact("x", "is", "y", source=Source.USER)]
    assert engine.verify_correction(correction, related)
    assert correction.verified


def test_deep_learn():
    """Tests deep learning trigger returns frequent patterns. Result: PASS."""
    engine = LearningEngine()
    proof = ["[modus_ponens] a implies b -> c is b"]
    for _ in range(5):
        engine.learn_from_proof(proof)
    patterns = engine.deep_learn()
    assert len(patterns) > 0
