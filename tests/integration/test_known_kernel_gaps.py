"""Known kernel gaps, each owned by a later Phase 1 stage (found while red-teaming Stage 1.1, #27).

Every test states the correct behaviour and is a strict expected failure: when
the owning stage fixes the gap, the test starts passing and pytest reports it,
so the marker must be removed in that stage. Nothing here can drift silently.
"""
import pytest

from kernel.engine import InferenceEngine
from kernel.facts import Fact

STAGE_1_4 = pytest.mark.xfail(strict=True, reason="Stage 1.4 (#30): proofs record only one premise")
STAGE_1_5 = pytest.mark.xfail(strict=True, reason="Stage 1.5 (#31): no exceptions or recorded contradictions")


def run(*batches):
    engine = InferenceEngine()
    for batch in batches:
        engine.add_facts(batch)
        engine.infer()
    return engine







def test_proof_names_every_premise():
    """Fixed in Stage 1.2 (#28): every derivation records all of its premises."""
    engine = run([Fact("man", "implies", "mortal"), Fact("socrates", "is", "man")])
    proof = engine.beliefs[("socrates", "is", "mortal")].proof_chain[0]
    assert "socrates is man" in proof and "man implies mortal" in proof


@STAGE_1_4
def test_proof_is_a_structured_record_with_its_confidence():
    engine = run([Fact("man", "implies", "mortal", confidence=0.8), Fact("socrates", "is", "man")])
    record = engine.beliefs[("socrates", "is", "mortal")].proofs[0]
    assert record.rule == "modus_ponens"
    assert set(record.premises) == {("man", "implies", "mortal"), ("socrates", "is", "man")}
    assert abs(record.confidence - 0.8) < 1e-9


@STAGE_1_5
def test_specific_evidence_overrides_a_general_default():
    engine = run([Fact("bird", "all_are", "flier"), Fact("penguin", "is", "bird"),
                  Fact("pingu", "is", "penguin"), Fact("pingu", "not_is", "flier")])
    assert not engine.query("pingu", "is", "flier")
    assert engine.resolver.get_contradictions()
