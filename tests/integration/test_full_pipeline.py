"""Full integration tests: Kernel → Memory → Learning pipeline.

Verifies end-to-end flow from reasoning through memory to learning.
"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine
from memory.system import MemorySystem
from learning.engine import LearningEngine


def test_kernel_to_memory_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        memory.engine.add_facts([
            Fact("bird", "all_are", "flies", source=Source.USER),
            Fact("tweety", "is", "bird", source=Source.USER),
        ])
        memory.engine.infer()
        for belief in memory.engine.query():
            memory.store(belief.fact)
        assert memory.count() > 0
        results = memory.recall("tweety")
        assert len(results) > 0


def test_memory_to_learning_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        learning = LearningEngine(memory_system=memory)
        learning.engine.add_facts([
            Fact("bird", "all_are", "flies", source=Source.USER),
            Fact("tweety", "is", "bird", source=Source.USER),
        ])
        learning.engine.infer()
        for belief in learning.engine.query():
            learning.learn_from_proof(belief.proof_chain)
        patterns = learning.pattern_extractor.get_patterns(min_usage=1)
        assert isinstance(patterns, list)


def test_learn_then_apply():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        learning = LearningEngine(memory_system=memory)
        learning.engine.add_facts([
            Fact("bird", "all_are", "flies", source=Source.USER),
            Fact("tweety", "is", "bird", source=Source.USER),
        ])
        learning.engine.infer()
        for belief in learning.engine.query():
            learning.learn_from_proof(belief.proof_chain)
            memory.store(belief.fact)
        learning.engine.add_facts([
            Fact("fish", "all_are", "swims", source=Source.USER),
            Fact("nemo", "is", "fish", source=Source.USER),
        ])
        learning.engine.infer()
        result = learning.engine.query(subject="nemo", predicate="is", object="swims")
        assert len(result) > 0


def test_error_correction_in_pipeline():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        learning = LearningEngine(memory_system=memory)
        learning.engine.add_facts([
            Fact("penguin", "is", "bird", source=Source.USER),
            Fact("bird", "all_are", "flies", source=Source.USER),
            Fact("penguin", "not_is", "flies", source=Source.USER),
        ])
        learning.engine.infer()
        contradictions = learning.engine.query(predicate="contradiction")
        assert len(contradictions) > 0
        original = Fact("penguin", "not_is", "flies", source=Source.DEDUCED)
        corrected = Fact("penguin", "is", "flies", source=Source.USER)
        correction = learning.submit_correction(original, corrected, 1.0)
        assert learning.should_override_correction(correction)


def test_skill_persistence_in_pipeline():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        learning = LearningEngine(
            skills_dir=os.path.join(tmpdir, "skills"),
            memory_system=memory
        )
        learning.engine.add_facts([
            Fact("bird", "all_are", "flies", source=Source.USER),
            Fact("tweety", "is", "bird", source=Source.USER),
        ])
        learning.engine.infer()
        for belief in learning.engine.query():
            learning.learn_from_proof(belief.proof_chain)
        learning.compile_skill("bird_flies", "logic",
            [Fact("bird", "all_are", "flies", source=Source.USER)],
            Fact("tweety", "is", "flies", source=Source.DEDUCED), 1.0)
        zip_path = os.path.join(tmpdir, "skills.zip")
        learning.export_skills(zip_path)
        learning2 = LearningEngine(
            skills_dir=os.path.join(tmpdir, "skills2"),
            memory_system=memory
        )
        count = learning2.import_skills(zip_path)
        assert count == 1
        skill = learning2.get_skill("bird_flies")
        assert skill is not None


def test_cross_domain_in_pipeline():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = MemorySystem(db_path=os.path.join(tmpdir, "test.db"))
        learning = LearningEngine(memory_system=memory)
        python_facts = [
            Fact("python_function", "has_input", "parameters", source=Source.USER),
            Fact("python_function", "has_output", "return_value", source=Source.USER),
        ]
        for fact in python_facts:
            learning.engine.add_fact(fact)
            memory.store(fact)
        learning.add_manual_analogy("python_function", "math_function", {
            "parameters": "domain", "return_value": "codomain",
        })
        math_facts = [
            Fact("math_function", "has_input", "domain", source=Source.USER),
            Fact("math_function", "has_output", "codomain", source=Source.USER),
        ]
        for fact in math_facts:
            learning.engine.add_fact(fact)
            memory.store(fact)
        analogies = learning.get_analogies("python_function")
        assert len(analogies) > 0
        assert analogies[0].source == "manual"
