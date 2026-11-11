"""PLN-style revision: a second independent derivation updates evidence."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.engine import InferenceEngine
from kernel.facts import Belief, Fact
from kernel.truth import TruthValue, revision


def test_revision_of_equal_evidence():
    t = revision(TruthValue(0.8, 0.5), TruthValue(0.8, 0.5))
    assert abs(t.strength - 0.8) < 1e-9
    assert abs(t.confidence - (2 / 3)) < 1e-9


def test_revision_is_weighted_mean():
    t = revision(TruthValue(0.9, 0.75), TruthValue(0.5, 0.5))
    assert 0.5 < t.strength < 0.9
    assert t.confidence > 0.5


def test_belief_revise_tracks_evidence():
    belief = Belief(fact=Fact("x", "is", "y", confidence=0.81))
    belief.revise(0.9, "[rule]")
    assert belief.evidence == 2
    assert len(belief.proof_chain) == 1
    assert abs(belief.confidence - 0.855) < 1e-9


FIRST = [Fact("a", "implies", "b", confidence=0.9), Fact("a", "is", "a")]
SECOND = [Fact("a", "implies", "m", confidence=0.9), Fact("m", "implies", "b", confidence=0.9)]


def test_a_second_derivation_adds_evidence_and_keeps_the_best_confidence():
    """Stage 1.2 (#28): confidence is the best derivation, evidence counts distinct derivations.

    Before, the second path was folded in by PLN revision (giving 0.855), but
    only when it arrived in a later pass: the same facts in one batch gave
    0.9. Both paths share the premise "a is a", so they are not independent
    evidence and revision double-counted it.
    """
    incremental = InferenceEngine()
    incremental.add_facts(FIRST)
    incremental.infer()
    incremental.add_facts(SECOND)
    incremental.infer()
    batch = InferenceEngine()
    batch.add_facts(FIRST + SECOND)
    batch.infer()

    for engine in (incremental, batch):
        belief = engine.query("a", "is", "b")[0]
        assert belief.evidence == 2
        assert len(belief.proof_chain) == 2
        assert abs(belief.confidence - 0.9) < 1e-9


def test_a_better_derivation_raises_the_belief_and_its_consequences():
    engine = InferenceEngine()
    engine.add_facts([Fact("x", "is", "a"), Fact("a", "implies", "b", confidence=0.5),
                      Fact("b", "implies", "c")])
    engine.infer()
    assert abs(engine.query("x", "is", "c")[0].confidence - 0.5) < 1e-9
    engine.add_fact(Fact("a", "implies", "m", confidence=0.9))
    engine.add_fact(Fact("m", "implies", "b"))
    engine.infer()
    assert abs(engine.query("x", "is", "b")[0].confidence - 0.9) < 1e-9
    assert abs(engine.query("x", "is", "c")[0].confidence - 0.9) < 1e-9


def test_single_pass_confidence_unchanged():
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "implies", "b", confidence=0.9), Fact("a", "is", "a")])
    engine.infer()
    belief = engine.query("a", "is", "b")[0]
    assert abs(belief.confidence - 0.9) < 1e-9
    assert belief.evidence == 1
