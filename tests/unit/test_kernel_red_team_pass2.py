"""Second red-team pass on the kernel (Stage 1.1, #27).

Each test is a defect found after the first round of fixes, with the input
that showed it.
"""
from __future__ import annotations

import logging

from kernel.engine import InferenceEngine
from kernel.facts import Fact, Source
from kernel.foundations import TRUE, canonical_fact


def engine_with(*triples, source=Source.USER):
    engine = InferenceEngine()
    engine.add_facts([Fact(*t, source=source) for t in triples])
    return engine


# --- non-canonical input used to be invisible to the propositional rules


def test_canonical_fact_moves_negation_into_the_predicate():
    assert str(canonical_fact(Fact("not:rain", "is", TRUE))) == "rain not_is true"
    assert str(canonical_fact(Fact("not:rain", "not_is", TRUE))) == "rain is true"
    assert str(canonical_fact(Fact("not:not:rain", "is", TRUE))) == "rain is true"
    assert str(canonical_fact(Fact("not:not:a", "or", "not:not:not:b"))) == "a or not:b"


def test_canonical_fact_leaves_class_facts_alone():
    f = Fact("tweety", "is", "bird")
    assert canonical_fact(f) is f


def test_negated_input_feeds_modus_tollens():
    # "not:rain is true" means rain fails; with wet -> rain, wet fails.
    engine = engine_with(("not:rain", "is", TRUE), ("wet", "implies", "rain"))
    engine.infer()
    assert "wet not_is true" in engine.beliefs


def test_double_negated_input_feeds_modus_ponens():
    engine = engine_with(("not:not:rain", "is", TRUE), ("rain", "implies", "wet"))
    engine.infer()
    assert "wet is true" in engine.beliefs


def test_negated_input_is_a_contradiction_with_its_positive():
    engine = engine_with(("rain", "is", TRUE), ("not:rain", "is", TRUE))
    engine.infer()
    assert "rain contradiction true" in engine.beliefs


def test_the_same_statement_written_two_ways_is_one_belief():
    engine = engine_with(("rain", "not_is", TRUE), ("not:rain", "is", TRUE))
    assert len(engine.beliefs) == 1


def test_prove_accepts_a_non_canonical_goal():
    engine = engine_with(("rain", "not_is", TRUE))
    assert engine.prove("not:rain", "is", TRUE) is not None
    assert engine.prove("not:not:rain", "not_is", TRUE) is not None


# --- retract used to drop every base fact that was not Source.USER


def test_retract_keeps_learned_and_inferred_facts():
    engine = InferenceEngine()
    engine.add_facts([
        Fact("tweety", "is", "bird", source=Source.LEARNED),
        Fact("bird", "implies", "animal", source=Source.INFERRED),
        Fact("rex", "is", "dog", source=Source.USER),
    ])
    engine.infer()
    engine.retract(Fact("rex", "is", "dog"))
    assert "tweety is bird" in engine.beliefs
    assert "bird implies animal" in engine.beliefs
    assert "tweety is animal" in engine.beliefs
    assert "rex is dog" not in engine.beliefs


def test_retract_removes_consequences_of_a_learned_fact():
    engine = engine_with(("tweety", "is", "bird"), ("bird", "implies", "animal"), source=Source.LEARNED)
    engine.infer()
    engine.retract(Fact("bird", "implies", "animal"))
    assert "tweety is animal" not in engine.beliefs


def test_retract_accepts_a_non_canonical_fact():
    engine = engine_with(("rain", "not_is", TRUE))
    engine.retract(Fact("not:rain", "is", TRUE))
    assert not engine.beliefs


# --- infer() used to stop at max_iterations without saying so


def test_infer_reports_when_it_stops_early(caplog):
    engine = engine_with(("x", "is", "c0"), *[(f"c{i}", "implies", f"c{i + 1}") for i in range(30)])
    with caplog.at_level(logging.WARNING, logger="kernel.engine"):
        engine.infer(max_iterations=10)
    assert engine.saturated is False
    assert "stopped after 10 iterations" in caplog.text
    engine.infer()
    assert engine.saturated is True
    assert "x is c30" in engine.beliefs


def test_infer_is_saturated_after_a_normal_run():
    engine = engine_with(("x", "is", "a"), ("a", "implies", "b"))
    engine.infer()
    assert engine.saturated is True
