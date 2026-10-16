"""High-value red team tests for V0.4 Continuous Learning.

Tests edge cases, concurrency, corruption, and failure modes.
"""
import sys, os, tempfile, threading, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from learning.engine import LearningEngine


def test_concurrent_learning_and_reasoning():
    errors = []
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = LearningEngine(skills_dir=os.path.join(tmpdir, "skills"))
        def learner():
            try:
                for i in range(10):
                    engine.learn_from_proof([f"[modus_ponens] a{i} implies b{i} -> c{i} is b{i}"])
            except Exception as e:
                errors.append(str(e))
        def reasoner():
            try:
                for i in range(10):
                    engine.engine.add_fact(Fact(f"x{i}", "is", f"y{i}", source=Source.USER))
                    engine.engine.infer()
            except Exception as e:
                errors.append(str(e))
        t1 = threading.Thread(target=learner)
        t2 = threading.Thread(target=reasoner)
        t1.start(); t2.start()
        t1.join(); t2.join()
        assert len(errors) == 0


def test_malformed_skill_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = os.path.join(tmpdir, "skills")
        os.makedirs(os.path.join(skills_dir, "logic"), exist_ok=True)
        with open(os.path.join(skills_dir, "logic", "bad.json"), "w") as f:
            f.write("{invalid json")
        engine = LearningEngine(skills_dir=skills_dir)
        assert len(engine.skill_compiler.skills) == 0


def test_circular_pattern_dependency():
    engine = LearningEngine()
    proof1 = ["[modus_ponens] a implies b -> c is b"]
    proof2 = ["[modus_ponens] c is b -> a implies b"]
    engine.learn_from_proof(proof1)
    engine.learn_from_proof(proof2)
    patterns = engine.pattern_extractor.get_patterns(min_usage=1)
    assert isinstance(patterns, list)


def test_conflicting_skills_same_name():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = LearningEngine(skills_dir=os.path.join(tmpdir, "skills"))
        engine.compile_skill("conflict", "logic",
            [Fact("a", "implies", "b", source=Source.USER)],
            Fact("a", "is", "b", source=Source.DEDUCED), 0.95)
        engine.compile_skill("conflict", "logic",
            [Fact("x", "implies", "y", source=Source.USER)],
            Fact("x", "is", "y", source=Source.DEDUCED), 0.50)
        skill = engine.get_skill("conflict")
        assert skill is not None
        assert skill.confidence == 0.50


def test_large_scale_pattern_extraction():
    engine = LearningEngine()
    start = time.time()
    for i in range(100):
        engine.learn_from_proof([f"[modus_ponens] a{i} implies b{i} -> c{i} is b{i}"])
    elapsed = time.time() - start
    assert elapsed < 30.0
    patterns = engine.pattern_extractor.get_patterns(min_usage=1)
    assert len(patterns) > 0


def test_skill_with_zero_confidence():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = LearningEngine(skills_dir=os.path.join(tmpdir, "skills"))
        skill = engine.compile_skill("zero", "logic",
            [Fact("a", "implies", "b", source=Source.USER)],
            Fact("a", "is", "b", source=Source.DEDUCED), 0.0)
        assert not engine.should_use_skill(skill)
        assert not engine.should_override_with_skill(skill)


def test_cross_domain_no_common_predicates():
    engine = LearningEngine()
    source = [Fact("a", "has", "b", source=Source.USER)]
    target = [Fact("x", "contains", "y", source=Source.USER)]
    analogy = engine.map_domains("a", "x", source, target)
    assert analogy is None


def test_error_correction_zero_confidence():
    engine = LearningEngine()
    correction = engine.submit_correction(
        Fact("a", "is", "b"), Fact("a", "is", "c"), 0.0)
    assert not engine.should_override_correction(correction)
    assert not engine.should_resolve_conflict(correction)


def test_empty_skills_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = os.path.join(tmpdir, "empty_skills")
        os.makedirs(skills_dir)
        engine = LearningEngine(skills_dir=skills_dir)
        assert len(engine.skill_compiler.skills) == 0
        assert engine.get_usable_skills(0.99) == []


def test_learning_under_concurrent_load():
    errors = []
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = LearningEngine(skills_dir=os.path.join(tmpdir, "skills"))
        def worker(wid):
            try:
                for i in range(20):
                    engine.learn_from_proof([f"[modus_ponens] w{wid}_a{i} implies b{i} -> c{i} is b{i}"])
                    engine.engine.add_fact(Fact(f"w{wid}_x{i}", "is", f"y{i}", source=Source.USER))
                    engine.engine.infer()
            except Exception as e:
                errors.append(f"{wid}: {e}")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(errors) == 0
