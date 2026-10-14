"""Comprehensive tests for ADAM's logical kernel."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kernel.facts import Fact, Source
from kernel.foundations import (
    modus_ponens,
    modus_tollens,
    transitivity,
    universal_instantiation,
    existential_generalization,
    equality_substitution,
    disjunctive_syllogism,
    contradiction_detection,
    de_morgan_and,
    de_morgan_or,
    double_negation,
    conditional_proof,
    universal_generalization,
)
from kernel.engine import InferenceEngine
from kernel.graph import KnowledgeGraph
from kernel.contradictions import ContradictionResolver
from kernel.unification import unify, find_unifiable


def test_modus_ponens():
    implies = Fact("bird", "implies", "flies")
    is_bird = Fact("tweety", "is", "bird")
    result = modus_ponens(implies, is_bird)
    assert result is not None
    assert result.subject == "tweety"
    assert result.predicate == "is"
    assert result.object == "flies"
    assert result.source == Source.DEDUCED


def test_modus_ponens_no_match():
    implies = Fact("bird", "implies", "flies")
    is_mammal = Fact("tweety", "is", "mammal")
    result = modus_ponens(implies, is_mammal)
    assert result is None


def test_modus_tollens():
    implies = Fact("code", "implies", "runs")
    not_runs = Fact("code", "not_is", "runs")
    result = modus_tollens(implies, not_runs)
    assert result is not None
    assert result.subject == "code"
    assert result.predicate == "not_is"
    assert result.object == "code"


def test_transitivity():
    p_implies_q = Fact("a", "implies", "b")
    q_implies_r = Fact("b", "implies", "c")
    result = transitivity(p_implies_q, q_implies_r)
    assert result is not None
    assert result.subject == "a"
    assert result.predicate == "implies"
    assert result.object == "c"


def test_transitivity_no_chain():
    p_implies_q = Fact("a", "implies", "b")
    r_implies_s = Fact("r", "implies", "s")
    result = transitivity(p_implies_q, r_implies_s)
    assert result is None


def test_universal_instantiation():
    all_birds_fly = Fact("bird", "all_are", "flies")
    tweety_is_bird = Fact("tweety", "is", "bird")
    result = universal_instantiation(all_birds_fly, tweety_is_bird)
    assert result is not None
    assert result.subject == "tweety"
    assert result.predicate == "is"
    assert result.object == "flies"


def test_existential_generalization():
    tweety_is_bird = Fact("tweety", "is", "bird")
    result = existential_generalization(tweety_is_bird)
    assert result is not None
    assert result.subject == "exists"
    assert result.predicate == "is"
    assert result.object == "bird"


def test_equality_substitution_in_subject():
    a_equals_b = Fact("a", "equals", "b")
    a_is_c = Fact("a", "is", "c")
    result = equality_substitution(a_equals_b, a_is_c)
    assert result is not None
    assert result.subject == "b"
    assert result.predicate == "is"
    assert result.object == "c"


def test_equality_substitution_in_object():
    a_equals_b = Fact("a", "equals", "b")
    c_is_a = Fact("c", "is", "a")
    result = equality_substitution(a_equals_b, c_is_a)
    assert result is not None
    assert result.subject == "c"
    assert result.predicate == "is"
    assert result.object == "b"


def test_disjunctive_syllogism():
    a_or_b = Fact("a", "or", "b")
    not_a = Fact("a", "not_is", "a")
    result = disjunctive_syllogism(a_or_b, not_a)
    assert result is not None
    assert result.subject == "b"
    assert result.predicate == "is"
    assert result.object == "true"


def test_contradiction_detection():
    p = Fact("x", "is", "y")
    not_p = Fact("x", "not_is", "y")
    result = contradiction_detection(p, not_p)
    assert result is not None
    assert result.subject == "x"
    assert result.predicate == "contradiction"
    assert result.object == "y"


def test_contradiction_no_false_positive():
    p = Fact("x", "is", "y")
    q = Fact("x", "is", "z")
    result = contradiction_detection(p, q)
    assert result is None


def test_de_morgan_and():
    not_a_and_b = Fact("a", "not_and", "b")
    result = de_morgan_and(not_a_and_b)
    assert result is not None
    assert result.predicate == "or"


def test_de_morgan_or():
    not_a_or_b = Fact("a", "not_or", "b")
    result = de_morgan_or(not_a_or_b)
    assert result is not None
    assert result.predicate == "and"


def test_double_negation():
    not_not_p = Fact("p", "not_not", "true")
    result = double_negation(not_not_p)
    assert result is not None
    assert result.subject == "p"
    assert result.predicate == "is"
    assert result.object == "true"


def test_conditional_proof():
    assumes = Fact("p", "assumes", "p")
    derives = Fact("q", "derives", "q")
    result = conditional_proof(assumes, derives)
    assert result is not None
    assert result.subject == "p"
    assert result.predicate == "implies"
    assert result.object == "q"


def test_universal_generalization():
    arbitrary_c = Fact("arbitrary_c", "is", "mortal")
    result = universal_generalization(arbitrary_c)
    assert result is not None
    assert result.subject == "all_c"
    assert result.predicate == "all_are"
    assert result.object == "mortal"


def test_fact_validation():
    try:
        Fact("", "is", "y")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_fact_negation():
    p = Fact("x", "is", "y", confidence=0.8)
    not_p = p.negate()
    assert not_p.subject == "x"
    assert not_p.predicate == "not_is"
    assert not_p.object == "y"
    assert abs(not_p.confidence - 0.2) < 0.001


def test_engine_chained_deduction():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b"),
        Fact("b", "implies", "c"),
        Fact("c", "implies", "d"),
        Fact("a", "is", "a"),
    ])
    new_facts = engine.infer()
    deduced = {str(f) for f in new_facts}
    assert "a is b" in deduced
    assert "a is c" in deduced
    assert "a is d" in deduced


def test_engine_contradiction_detection():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "all_are", "flies"),
        Fact("penguin", "is", "bird"),
        Fact("penguin", "not_is", "flies"),
    ])
    engine.infer()
    contradictions = engine.query(predicate="contradiction")
    assert len(contradictions) > 0


def test_engine_reasoning_trace():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("bird", "implies", "flies"),
        Fact("tweety", "is", "bird"),
    ])
    engine.infer()
    trace = engine.get_trace()
    assert len(trace) > 0
    assert any("tweety" in t for t in trace)


def test_engine_query():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("cat", "is", "mammal"),
        Fact("dog", "is", "mammal"),
        Fact("fish", "is", "not_mammal"),
    ])
    mammals = engine.query(predicate="is")
    assert len(mammals) == 3


def test_knowledge_graph():
    graph = KnowledgeGraph()
    graph.add_facts([
        Fact("a", "is", "b"),
        Fact("b", "is", "c"),
        Fact("c", "is", "d"),
    ])
    related = graph.get_related("b", hops=2)
    assert len(related) > 0
    path = graph.find_path("a", "d")
    assert path is not None
    assert path == ["a", "b", "c", "d"]


def test_knowledge_graph_cycle():
    graph = KnowledgeGraph()
    graph.add_facts([
        Fact("a", "is", "b"),
        Fact("b", "is", "c"),
        Fact("c", "is", "a"),
    ])
    related = graph.get_related("a", hops=3)
    assert len(related) > 0


def test_contradiction_resolver():
    from kernel.facts import Belief
    resolver = ContradictionResolver()
    fact_a = Fact("x", "is", "y", confidence=0.9, source=Source.USER)
    fact_b = Fact("x", "not_is", "y", confidence=0.7, source=Source.DEDUCED)
    belief_a = Belief(fact=fact_a)
    belief_b = Belief(fact=fact_b)
    result = resolver.check(belief_b, [belief_a])
    assert result is not None
    assert result.fact.subject == "x"


def test_unification():
    fact_a = Fact("?x", "is", "mortal")
    fact_b = Fact("socrates", "is", "mortal")
    bindings = unify(fact_a, fact_b)
    assert bindings is not None
    assert bindings.get("?x") == "socrates"


def test_unification_no_match():
    fact_a = Fact("x", "is", "mortal")
    fact_b = Fact("y", "is", "immortal")
    bindings = unify(fact_a, fact_b)
    assert bindings is None


def test_unification_occurs_check():
    fact_a = Fact("?x", "is", "?x")
    fact_b = Fact("y", "is", "z")
    bindings = unify(fact_a, fact_b)
    assert bindings is None


def test_find_unifiable():
    facts = [
        Fact("socrates", "is", "mortal"),
        Fact("plato", "is", "mortal"),
        Fact("cat", "is", "animal"),
    ]
    pattern = Fact("?x", "is", "mortal")
    results = find_unifiable(pattern, facts)
    assert len(results) == 2


def test_confidence_propagation():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b", confidence=0.9),
        Fact("a", "is", "a", confidence=0.8),
    ])
    engine.infer()
    beliefs = engine.query(subject="a")
    assert len(beliefs) > 0
    assert beliefs[0].confidence <= 0.9


def test_empty_engine():
    engine = InferenceEngine()
    new_facts = engine.infer()
    assert len(new_facts) == 0


def test_engine_max_iterations():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("a", "implies", "b"),
        Fact("b", "implies", "a"),
        Fact("a", "is", "a"),
    ])
    new_facts = engine.infer(max_iterations=10)
    assert len(new_facts) > 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
