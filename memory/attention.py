"""ECAN-inspired attention allocation.

In OpenCog's Economic Attention Network, atoms compete for a finite budget
of short-term importance (STI) that decays and is re-earned by use. This is
a small version of that idea: facts accumulate importance when recalled and
lose it on every decay tick, so recall ranks by what the system has actually
been using rather than by insertion order.

chisel: in-memory only, importance resets on restart; persist the snapshot
into facts.metadata if attention must survive sessions.
"""

from __future__ import annotations


class AttentionBank:
    def __init__(self, decay: float = 0.9, stimulus: float = 1.0, sti_cap: float = 100.0):
        self.decay_rate = decay
        self.stimulus = stimulus
        self.sti_cap = sti_cap
        self.sti: dict[str, float] = {}
        self.lti: dict[str, float] = {}

    def stimulate(self, key: str, amount: float | None = None) -> None:
        amount = self.stimulus if amount is None else amount
        self.sti[key] = min(self.sti_cap, self.sti.get(key, 0.0) + amount)
        self.lti[key] = self.lti.get(key, 0.0) * 0.99 + amount * 0.1

    def decay(self) -> None:
        for key, value in self.sti.items():
            self.sti[key] = value * self.decay_rate

    def score(self, key: str) -> float:
        return self.sti.get(key, 0.0) * 0.8 + self.lti.get(key, 0.0) * 0.2

    def rank(self, facts: list) -> list:
        """Stable sort by attention; ties keep their previous order."""
        return sorted(facts, key=lambda f: self.score(str(f)), reverse=True)
