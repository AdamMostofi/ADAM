"""Universal generalization: an arbitrary member of T is X gives "T all_are X".

Stage 1.1 (#27) fixes: the rule was registered on "all_are" but needs an "is"
fact, so it never fired in the engine; and it produced the meaningless
subject "all_c" instead of the class.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.engine import InferenceEngine
from kernel.facts import Fact
from kernel.foundations import universal_generalization


def triple(f):
    return (f.subject, f.predicate, f.object)


def test_arbitrary_member_generalizes_to_its_class():
    assert triple(universal_generalization(Fact("arbitrary_man", "is", "mortal"))) == ("man", "all_are", "mortal")


def test_fires_through_the_engine_and_then_instantiates():
    engine = InferenceEngine()
    engine.add_facts([Fact("arbitrary_man", "is", "mortal"), Fact("socrates", "is", "man")])
    engine.infer()
    assert engine.query("man", "all_are", "mortal")
    assert engine.query("socrates", "is", "mortal")


def test_non_arbitrary_subject_gives_nothing():
    assert universal_generalization(Fact("socrates", "is", "mortal")) is None


def test_bare_prefix_gives_nothing():
    assert universal_generalization(Fact("arbitrary_", "is", "mortal")) is None


def test_propositions_give_nothing():
    assert universal_generalization(Fact("arbitrary_man", "is", "true")) is None


def test_wrong_predicate():
    assert universal_generalization(Fact("arbitrary_c", "equals", "mortal")) is None


def test_confidence_decay():
    r = universal_generalization(Fact("arbitrary_man", "is", "mortal", confidence=0.9))
    assert r and r.confidence < 0.9
