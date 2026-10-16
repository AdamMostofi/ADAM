"""Deep tests and high-value red team for V0.2 Logical Kernel.

Tests multi-step reasoning correctness, confidence accuracy, all rules together,
thread safety, large-scale performance, and edge cases.
"""
import sys, os, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine


def test_multi_step_reasoning_correctness():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", source=Source.USER),
        Fact("b", "implies", "c", source=Source.USER),
        Fact("c", "implies", "d", source=Source.USER),
        Fact("d", "implies", "e", source=Source.USER),
        Fact("a", "is", "a", source=Source.USER),
    ])
    engine.infer()
    assert len(engine.query(subject="a", predicate="is", object="e")) > 0
    assert len(engine.query(subject="a", predicate="implies", object="e")) > 0
    assert len(engine.query(subject="b", predicate="implies", object="d")) > 0


def test_confidence_propagation_accuracy():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", confidence=0.9, source=Source.USER),
        Fact("b", "implies", "c", confidence=0.9, source=Source.USER),
        Fact("c", "implies", "d", confidence=0.9, source=Source.USER),
        Fact("a", "is", "a", confidence=1.0, source=Source.USER),
    ])
    engine.infer()
    result = [b for b in engine.query(subject="a", predicate="is", object="d")]
    assert len(result) > 0
    assert abs(result[0].confidence - 0.729) < 0.001


def test_all_16_rules_together():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "all_are", "flies", source=Source.USER),
        Fact("penguin", "is", "bird", source=Source.USER),
        Fact("tweety", "is", "penguin", source=Source.USER),
        Fact("op", "equals", "operation", source=Source.USER),
        Fact("operation", "is", "process", source=Source.USER),
        Fact("sunny", "or", "rainy", source=Source.USER),
        Fact("sunny", "not_is", "sunny", source=Source.USER),
        Fact("rainy", "implies", "wet", source=Source.USER),
        Fact("alive", "not_not", "true", source=Source.USER),
        Fact("alive", "implies", "breathing", source=Source.USER),
    ])
    engine.infer()
    assert len(engine.query(subject="tweety", predicate="is", object="bird")) > 0
    assert len(engine.query(subject="tweety", predicate="is", object="flies")) > 0
    assert len(engine.query(subject="op", predicate="is", object="process")) > 0
    assert len(engine.query(object="wet")) > 0
    assert len(engine.query(object="breathing")) > 0


def test_thread_safety_heavy_load():
    errors = []
    engine = InferenceEngine()
    def worker(wid):
        try:
            for i in range(50):
                engine.add_fact(Fact(f"w{wid}_n{i}", "is", f"w{wid}_m{i}", source=Source.USER))
                engine.infer()
                engine.query(predicate="is")
        except Exception as e:
            errors.append(f"{wid}: {e}")
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(errors) == 0


def test_large_scale_1000_facts():
    engine = InferenceEngine()
    start = time.time()
    facts = [Fact(f"n{i}", "implies", f"n{i+1}") for i in range(1000)]
    facts.append(Fact("n0", "is", "n0"))
    engine.add_facts(facts)
    engine.infer(max_iterations=5000)
    elapsed = time.time() - start
    assert elapsed < 60.0
    assert len(engine.query(subject="n0", predicate="is", object="n1000")) > 0


def test_empty_engine():
    engine = InferenceEngine()
    engine.infer()
    assert len(engine.query()) == 0


def test_single_fact_no_rules_apply():
    engine = InferenceEngine()
    engine.add_fact(Fact("x", "is", "y", source=Source.USER))
    engine.infer()
    assert len(engine.query(subject="x")) == 1


def test_circular_dependency_terminates():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", source=Source.USER),
        Fact("b", "implies", "a", source=Source.USER),
        Fact("a", "is", "a", source=Source.USER),
    ])
    new_facts = engine.infer(max_iterations=100)
    assert len(new_facts) > 0


def test_self_referential_fact():
    engine = InferenceEngine()
    engine.add_fact(Fact("a", "is", "a", source=Source.USER))
    engine.infer()
    assert len(engine.query(subject="a")) > 0


def test_contradiction_in_nested_deduction():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "all_are", "b", source=Source.USER),
        Fact("b", "all_are", "c", source=Source.USER),
        Fact("x", "is", "a", source=Source.USER),
        Fact("x", "not_is", "c", source=Source.USER),
    ])
    engine.infer()
    contradictions = engine.query(predicate="contradiction")
    assert len(contradictions) > 0


def test_retract_cascading_dependents():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", source=Source.USER),
        Fact("b", "implies", "c", source=Source.USER),
        Fact("c", "implies", "d", source=Source.USER),
        Fact("a", "is", "a", source=Source.USER),
    ])
    engine.infer()
    assert len(engine.query(subject="a", predicate="is", object="d")) > 0
    engine.retract(Fact("a", "implies", "b"))
    assert len(engine.query(subject="a", predicate="is", object="d")) == 0


def test_query_with_no_matches():
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "is", "b", source=Source.USER)])
    engine.infer()
    assert len(engine.query(subject="nonexistent")) == 0
    assert len(engine.query(predicate="nonexistent")) == 0
    assert len(engine.query(object="nonexistent")) == 0


def test_fact_validation_edge_cases():
    try:
        Fact("", "is", "y")
        assert False
    except ValueError:
        pass
    try:
        Fact("x", "", "y")
        assert False
    except ValueError:
        pass
    try:
        Fact("x", "is", "")
        assert False
    except ValueError:
        pass
    try:
        Fact("x", "is", "y", confidence=-0.1)
        assert False
    except ValueError:
        pass
    try:
        Fact("x", "is", "y", confidence=1.1)
        assert False
    except ValueError:
        pass


def test_concurrent_infer_and_retract():
    errors = []
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", source=Source.USER),
        Fact("a", "is", "a", source=Source.USER),
    ])
    def inferer():
        try:
            for _ in range(20):
                engine.infer()
        except Exception as e:
            errors.append(str(e))
    def retractor():
        try:
            for _ in range(10):
                engine.retract(Fact("a", "implies", "b"))
                engine.add_fact(Fact("a", "implies", "b", source=Source.USER))
        except Exception as e:
            errors.append(str(e))
    t1 = threading.Thread(target=inferer)
    t2 = threading.Thread(target=retractor)
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert len(errors) == 0
