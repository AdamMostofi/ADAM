"""Attention bank: stimulus raises STI, decay lowers it, ranking follows."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact
from memory.attention import AttentionBank


def test_repeated_stimulus_outranks_single():
    bank = AttentionBank()
    bank.stimulate("x")
    bank.stimulate("y")
    bank.stimulate("y")
    assert bank.score("y") > bank.score("x")


def test_decay_reduces_score():
    bank = AttentionBank(decay=0.5)
    bank.stimulate("x")
    before = bank.score("x")
    bank.decay()
    assert bank.score("x") < before


def test_rank_puts_hot_fact_first():
    bank = AttentionBank()
    bank.stimulate("cold is x")
    for _ in range(5):
        bank.stimulate("hot is x")
    facts = [Fact("cold", "is", "x"), Fact("hot", "is", "x")]
    assert bank.rank(facts)[0].subject == "hot"
