"""Forward-chaining inference engine.

Takes a set of facts and rules, applies foundational logic,
and produces new deduced facts with full reasoning traces.
"""

from __future__ import annotations

from kernel.facts import Belief, Fact, Source
from kernel.foundations import (
    contradiction_detection,
    disjunctive_syllogism,
    equality_substitution,
    existential_generalization,
    modus_ponens,
    modus_tollens,
    transitivity,
    universal_instantiation,
)


class InferenceEngine:
    def __init__(self):
        self.beliefs: dict[str, Belief] = {}
        self.trace: list[str] = []

    def add_fact(self, fact: Fact) -> None:
        key = str(fact)
        if key not in self.beliefs:
            self.beliefs[key] = Belief(fact=fact)

    def add_facts(self, facts: list[Fact]) -> None:
        for f in facts:
            self.add_fact(f)

    def infer(self) -> list[Fact]:
        """Run forward chaining until no new facts can be deduced."""
        new_facts: list[Fact] = []
        facts_list = list(self.beliefs.values())

        for b in facts_list:
            f = b.fact
            results = self._apply_rules(f, facts_list)
            for result in results:
                key = str(result)
                if key not in self.beliefs:
                    proof = f"{b.fact} -> {result}"
                    self.beliefs[key] = Belief(fact=result, proof_chain=[proof])
                    new_facts.append(result)
                    self.trace.append(proof)

        return new_facts

    def _apply_rules(self, fact: Fact, all_beliefs: list[Belief]) -> list[Fact]:
        results: list[Fact] = []
        all_facts = [b.fact for b in all_beliefs]

        if fact.predicate == "implies":
            for other in all_facts:
                r = modus_ponens(fact, other)
                if r:
                    results.append(r)
                r = transitivity(fact, other)
                if r:
                    results.append(r)
            for other in all_facts:
                r = modus_tollens(fact, other)
                if r:
                    results.append(r)

        elif fact.predicate == "all_are":
            for other in all_facts:
                r = universal_instantiation(fact, other)
                if r:
                    results.append(r)

        elif fact.predicate == "equals":
            for other in all_facts:
                r = equality_substitution(fact, other)
                if r:
                    results.append(r)

        elif fact.predicate == "or":
            for other in all_facts:
                r = disjunctive_syllogism(fact, other)
                if r:
                    results.append(r)

        elif fact.predicate == "is":
            r = existential_generalization(fact)
            if r:
                results.append(r)

        for other in all_facts:
            r = contradiction_detection(fact, other)
            if r:
                results.append(r)

        return results

    def query(self, subject: str | None = None, predicate: str | None = None) -> list[Belief]:
        """Query beliefs by subject and/or predicate."""
        results = []
        for belief in self.beliefs.values():
            if subject and belief.fact.subject != subject:
                continue
            if predicate and belief.fact.predicate != predicate:
                continue
            results.append(belief)
        return results

    def get_trace(self) -> list[str]:
        return list(self.trace)
