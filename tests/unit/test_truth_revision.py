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


def test_engine_revises_across_inference_passes():
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "implies", "b", confidence=0.9), Fact("a", "is", "a")])
    engine.infer()
    first = engine.query("a", "is", "b")[0].confidence

    engine.add_facts([
        Fact("a", "implies", "m", confidence=0.9),
        Fact("m", "implies", "b", confidence=0.9),
    ])
    engine.infer()
    after = engine.query("a", "is", "b")[0]

    assert after.evidence == 2
    assert len(after.proof_chain) >= 2
    assert abs(after.confidence - 0.855) < 0.01
    assert after.confidence != first


def test_single_pass_confidence_unchanged():
    engine = InferenceEngine()
    engine.add_facts([Fact("a", "implies", "b", confidence=0.9), Fact("a", "is", "a")])
    engine.infer()
    belief = engine.query("a", "is", "b")[0]
    assert abs(belief.confidence - 0.9) < 1e-9
    assert belief.evidence == 1
