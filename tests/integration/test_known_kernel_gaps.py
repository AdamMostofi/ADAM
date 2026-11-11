"""Known kernel gaps, each owned by a later Phase 1 stage (found while red-teaming Stage 1.1, #27).

Every test states the correct behaviour and is a strict expected failure: when
the owning stage fixes the gap, the test starts passing and pytest reports it,
so the marker must be removed in that stage. Nothing here can drift silently.
Gaps already closed: Stage 1.2 (order), 1.3 (instance_of / subclass_of) and
1.4 (structured proofs; see tests/integration/test_derivations.py).
"""
import pytest

from kernel.engine import InferenceEngine
from kernel.facts import Fact

STAGE_1_5 = pytest.mark.xfail(strict=True, reason="Stage 1.5 (#31): no exceptions or recorded contradictions")


def run(*batches):
    engine = InferenceEngine()
    for batch in batches:
        engine.add_facts(batch)
        engine.infer()
    return engine


@STAGE_1_5
def test_specific_evidence_overrides_a_general_default():
    # Written with explicit predicates since Stage 1.3: with "is", the chain would not combine at all
    # and the first assertion would pass for the wrong reason.
    engine = run([Fact("bird", "subclass_of", "flier"), Fact("penguin", "subclass_of", "bird"),
                  Fact("pingu", "instance_of", "penguin"), Fact("pingu", "not_instance_of", "flier")])
    assert not engine.query("pingu", "instance_of", "flier")
    assert engine.resolver.get_contradictions()
