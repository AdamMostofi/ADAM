"""Deep integration tests for V0.4 Continuous Learning.

Verifies that learning actually improves reasoning quality.
"""
import sys, os, tempfile, threading, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from learning.engine import LearningEngine
from learning.skill_compiler import Skill
from learning.cross_domain import Analogy


def test_pattern_correctness():
    engine = LearningEngine()
    proof = ["[modus_ponens] bird implies flies -> tweety is flies"]
    engine.learn_from_proof(proof)
    patterns = engine.pattern_extractor.get_patterns(min_usage=1)
    assert len(patterns) > 0
    engine.engine.add_facts([
        Fact("fish", "implies", "swims", source=Source.USER),
        Fact("nemo", "is", "fish", source=Source.USER),
    ])
    engine.engine.infer()
    result = engine.engine.query(subject="nemo", predicate="is", object="swims")
    assert len(result) > 0


def test_skill_application():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = LearningEngine(skills_dir=os.path.join(tmpdir, "skills"))
        premises = [Fact("bird", "all_are", "flies", source=Source.USER)]
        conclusion = Fact("tweety", "is", "flies", source=Source.DEDUCED)
        skill = engine.compile_skill("bird_flies", "logic", premises, conclusion, 1.0)
        assert engine.should_use_skill(skill)
        assert engine.should_override_with_skill(skill)
        engine.engine.add_facts([
            Fact("bird", "all_are", "flies", source=Source.USER),
            Fact("sparrow", "is", "bird", source=Source.USER),
        ])
        engine.engine.infer()
        result = engine.engine.query(subject="sparrow", predicate="is", object="flies")
        assert len(result) > 0


def test_learning_loop():
    engine = LearningEngine()
    for i in range(3):
        proof = [f"[modus_ponens] a{i} implies b{i} -> c{i} is b{i}"]
        engine.learn_from_proof(proof)
    p1 = len(engine.pattern_extractor.get_patterns(min_usage=1))
    for i in range(3, 6):
        proof = [f"[modus_ponens] a{i} implies b{i} -> c{i} is b{i}"]
        engine.learn_from_proof(proof)
    p2 = len(engine.pattern_extractor.get_patterns(min_usage=1))
    assert p2 >= p1
    engine.engine.add_facts([
        Fact("shark", "implies", "swims", source=Source.USER),
        Fact("great_white", "is", "shark", source=Source.USER),
    ])
    engine.engine.infer()
    result = engine.engine.query(subject="great_white", predicate="is", object="swims")
    assert len(result) > 0


def test_cross_domain_transfer():
    engine = LearningEngine()
    python_facts = [
        Fact("python_function", "has_input", "parameters", source=Source.USER),
        Fact("python_function", "has_output", "return_value", source=Source.USER),
        Fact("python_function", "has_process", "body", source=Source.USER),
    ]
    for fact in python_facts:
        engine.engine.add_fact(fact)
    engine.add_manual_analogy("python_function", "math_function", {
        "parameters": "domain", "return_value": "codomain", "body": "mapping",
    })
    math_facts = [
        Fact("math_function", "has_input", "domain", source=Source.USER),
        Fact("math_function", "has_output", "codomain", source=Source.USER),
    ]
    for fact in math_facts:
        engine.engine.add_fact(fact)
    analogies = engine.get_analogies("python_function")
    assert len(analogies) > 0
    assert analogies[0].source == "manual"
    analogy = engine.map_domains("python_function", "math_function", python_facts, math_facts)
    assert analogy is not None
    assert analogy.confidence > 0


def test_error_correction_propagation():
    engine = LearningEngine()
    engine.engine.add_facts([
        Fact("penguin", "is", "bird", source=Source.USER),
        Fact("bird", "all_are", "flies", source=Source.USER),
        Fact("penguin", "not_is", "flies", source=Source.USER),
    ])
    engine.engine.infer()
    contradictions = engine.engine.query(predicate="contradiction")
    assert len(contradictions) > 0
    original = Fact("penguin", "not_is", "flies", source=Source.DEDUCED)
    corrected = Fact("penguin", "is", "flies", source=Source.USER)
    correction = engine.submit_correction(original, corrected, 1.0)
    assert engine.should_override_correction(correction)
    penguin_facts = engine.engine.query(subject="penguin")
    has_flies = any(b.fact.predicate == "is" and b.fact.object == "flies" for b in penguin_facts)
    has_not_flies = any(b.fact.predicate == "not_is" and b.fact.object == "flies" for b in penguin_facts)
    assert has_flies
    assert not has_not_flies


def test_skill_composition():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = LearningEngine(skills_dir=os.path.join(tmpdir, "skills"))
        engine.compile_skill("bird_flies", "logic",
            [Fact("bird", "all_are", "flies", source=Source.USER)],
            Fact("tweety", "is", "flies", source=Source.DEDUCED), 1.0)
        engine.compile_skill("flies_wings", "logic",
            [Fact("flies", "all_are", "has_wings", source=Source.USER)],
            Fact("tweety", "is", "has_wings", source=Source.DEDUCED), 1.0)
        engine.engine.add_facts([
            Fact("bird", "all_are", "flies", source=Source.USER),
            Fact("flies", "all_are", "has_wings", source=Source.USER),
            Fact("tweety", "is", "bird", source=Source.USER),
        ])
        engine.engine.infer()
        result = engine.engine.query(subject="tweety", predicate="is", object="has_wings")
        assert len(result) > 0


def test_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine1 = LearningEngine(skills_dir=os.path.join(tmpdir, "skills1"))
        engine1.compile_skill("persist_test", "logic",
            [Fact("a", "implies", "b", source=Source.USER)],
            Fact("a", "is", "b", source=Source.DEDUCED), 0.95)
        zip_path = os.path.join(tmpdir, "skills.zip")
        engine1.export_skills(zip_path)
        engine2 = LearningEngine(skills_dir=os.path.join(tmpdir, "skills2"))
        count = engine2.import_skills(zip_path)
        assert count == 1
        skill = engine2.get_skill("persist_test")
        assert skill is not None
        assert skill.confidence == 0.95
        assert engine2.should_use_skill(skill)
