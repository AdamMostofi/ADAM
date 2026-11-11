"""Known kernel gaps, each owned by a later Phase 1 stage (found while red-teaming Stage 1.1, #27).

Every test states the correct behaviour and is a strict expected failure: when
the owning stage fixes the gap, the test starts passing and pytest reports it,
so the marker must be removed in that stage. Nothing here can drift silently.
"""
import pytest

from kernel.engine import InferenceEngine
from kernel.facts import Fact

STAGE_1_2 = pytest.mark.xfail(strict=True, reason="Stage 1.2 (#28): rules fire in one premise position only")
STAGE_1_3 = pytest.mark.xfail(strict=True, reason="Stage 1.3 (#29): 'is' mixes membership and subclass")
STAGE_1_4 = pytest.mark.xfail(strict=True, reason="Stage 1.4 (#30): proofs record only one premise")
STAGE_1_5 = pytest.mark.xfail(strict=True, reason="Stage 1.5 (#31): no exceptions or recorded contradictions")


def run(*batches):
    engine = InferenceEngine()
    for batch in batches:
        engine.add_facts(batch)
        engine.infer()
    return engine


@STAGE_1_2
def test_modus_ponens_when_the_instance_arrives_after_the_rule():
    engine = run([Fact("fire", "implies", "hot")], [Fact("x", "is", "fire")])
    assert engine.query("x", "is", "hot")


@STAGE_1_2
def test_universal_instantiation_when_the_instance_arrives_later():
    engine = run([Fact("bird", "all_are", "flier")], [Fact("tweety", "is", "bird")])
    assert engine.query("tweety", "is", "flier")


@STAGE_1_2
def test_transitivity_when_the_first_link_arrives_later():
    engine = run([Fact("b", "is", "c")], [Fact("a", "is", "b")])
    engine2 = run([Fact("a", "is", "b")], [Fact("b", "is", "c")])
    assert engine.query("a", "is", "c") and engine2.query("a", "is", "c")


@STAGE_1_2
def test_different_facts_never_share_a_belief():
    engine = InferenceEngine()
    engine.add_facts([Fact("new york", "is", "city"), Fact("new", "york is", "city")])
    assert len(engine.beliefs) == 2


@STAGE_1_3
def test_membership_does_not_chain_through_a_class_of_classes():
    engine = run([Fact("rex", "is", "dog"), Fact("dog", "is", "species")])
    assert not engine.query("rex", "is", "species")


@STAGE_1_4
def test_proof_names_every_premise():
    engine = run([Fact("man", "implies", "mortal"), Fact("socrates", "is", "man")])
    proof = engine.beliefs["socrates is mortal"].proof_chain[0]
    assert "socrates is man" in proof and "man implies mortal" in proof


@STAGE_1_5
def test_specific_evidence_overrides_a_general_default():
    engine = run([Fact("bird", "all_are", "flier"), Fact("penguin", "is", "bird"),
                  Fact("pingu", "is", "penguin"), Fact("pingu", "not_is", "flier")])
    assert not engine.query("pingu", "is", "flier")
    assert engine.resolver.get_contradictions()
