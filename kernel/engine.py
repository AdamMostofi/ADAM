"""Forward-chaining inference engine with predicate-indexed agenda.

Uses a work queue (agenda) and predicate indexing to achieve O(n) inference
instead of O(n^3). Thread-safe via RLock.
"""

from __future__ import annotations

import collections
import threading

from kernel.facts import Belief, Fact, Source
from kernel.contradictions import ContradictionResolver
from kernel.foundations import contradiction_detection
from kernel.rules import BUILTIN_RULES, Rule


class InferenceEngine:
    def __init__(self):
        self.beliefs: dict[str, Belief] = {}
        self.trace: list[str] = []
        self.resolver = ContradictionResolver()
        self.lock = threading.RLock()
        self.agenda: collections.deque[Fact] = collections.deque()
        self.rules: list[Rule] = list(BUILTIN_RULES)
        self.rules_by_trigger: dict[str, list[Rule]] = {}
        for rule in self.rules:
            self.rules_by_trigger.setdefault(rule.trigger, []).append(rule)
        self.index: dict[str, set[str]] = {
            "implies": set(),
            "is": set(),
            "all_are": set(),
            "equals": set(),
            "or": set(),
            "not_is": set(),
            "not_and": set(),
            "not_or": set(),
            "not_not": set(),
            "assumes": set(),
            "derives": set(),
            "contradiction": set(),
        }

    def add_fact(self, fact: Fact) -> None:
        with self.lock:
            key = str(fact)
            if key not in self.beliefs:
                self.beliefs[key] = Belief(fact=fact)
                self.index.setdefault(fact.predicate, set()).add(key)
                self.agenda.append(fact)
                self._check_contradictions(fact)

    def add_facts(self, facts: list[Fact]) -> None:
        for f in facts:
            self.add_fact(f)

    def add_rule(self, rule: Rule) -> None:
        """Register a layer-2 rule (e.g. a compiled skill)."""
        with self.lock:
            if any(existing.name == rule.name for existing in self.rules):
                return
            self.rules.append(rule)
            self.rules_by_trigger.setdefault(rule.trigger, []).append(rule)
            self.index.setdefault(rule.trigger, set())
            if rule.partner is not None:
                self.index.setdefault(rule.partner, set())

    def retract(self, fact: Fact) -> None:
        with self.lock:
            key = str(fact)
            if key not in self.beliefs:
                return
            remaining = [
                b.fact for k, b in self.beliefs.items()
                if k != key and b.fact.source == Source.USER
            ]
            self.beliefs.clear()
            self.trace.clear()
            self.agenda.clear()
            for pred_set in self.index.values():
                pred_set.clear()
            self.add_facts(remaining)
            self.infer()

    def infer(self, max_iterations: int = 10000) -> list[Fact]:
        with self.lock:
            all_new_facts: list[Fact] = []
            touched: set[str] = set()
            iterations = 0
            while self.agenda and iterations < max_iterations:
                fact = self.agenda.popleft()
                results = self._apply_rules_indexed(fact)
                for rule_name, result in results:
                    key = str(result)
                    proof = f"[{rule_name}] {fact} -> {result}"
                    if key not in self.beliefs:
                        self.beliefs[key] = Belief(fact=result, proof_chain=[proof])
                        self.index.setdefault(result.predicate, set()).add(key)
                        self.agenda.append(result)
                        all_new_facts.append(result)
                        self.trace.append(proof)
                    elif key not in touched:
                        # chisel: revise only pre-existing beliefs, once per
                        # pass; intra-run duplicates collapse for determinism.
                        # Upgrade to full PLN revision when confidence
                        # contracts are re-baselined.
                        self.beliefs[key].revise(result.confidence, proof)
                        self.trace.append(proof)
                    touched.add(key)
                iterations += 1
            return all_new_facts

    def _apply_rules_indexed(self, fact: Fact) -> list[tuple[str, Fact]]:
        results: list[tuple[str, Fact]] = []
        for rule in self.rules_by_trigger.get(fact.predicate, ()):
            if rule.partner is None:
                outcome = rule.apply(fact)
                if outcome is not None:
                    for result in (outcome if isinstance(outcome, list) else [outcome]):
                        results.append((rule.name, result))
                continue
            for key in self.index.get(rule.partner, ()):
                outcome = rule.apply(fact, self.beliefs[key].fact)
                if outcome is None:
                    continue
                for result in (outcome if isinstance(outcome, list) else [outcome]):
                    results.append((rule.name, result))

        for other_key in self.index["is"]:
            other = self.beliefs[other_key].fact
            r = contradiction_detection(fact, other)
            if r:
                results.append(("contradiction_detection", r))
        for other_key in self.index["not_is"]:
            other = self.beliefs[other_key].fact
            r = contradiction_detection(fact, other)
            if r:
                results.append(("contradiction_detection", r))

        return results

    def _check_contradictions(self, new_fact: Fact) -> None:
        for key in self.index["is"]:
            if key == str(new_fact):
                continue
            belief = self.beliefs[key]
            contradiction = contradiction_detection(new_fact, belief.fact)
            if contradiction:
                self.add_fact(contradiction)
        for key in self.index["not_is"]:
            if key == str(new_fact):
                continue
            belief = self.beliefs[key]
            contradiction = contradiction_detection(new_fact, belief.fact)
            if contradiction:
                self.add_fact(contradiction)

    def query(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        object: str | None = None,
    ) -> list[Belief]:
        with self.lock:
            results = []
            for belief in self.beliefs.values():
                if subject and belief.fact.subject != subject:
                    continue
                if predicate and belief.fact.predicate != predicate:
                    continue
                if object and belief.fact.object != object:
                    continue
                results.append(belief)
            return results

    def query_pattern(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        object: str | None = None,
    ) -> list[tuple[Belief, dict[str, str]]]:
        """MeTTa-style match: `?x` terms bind; return (belief, bindings) pairs."""
        from kernel.unification import unify

        pattern = Fact(subject or "?s", predicate or "?p", object or "?o")
        with self.lock:
            matches = []
            for belief in self.beliefs.values():
                bindings = unify(pattern, belief.fact)
                if bindings is not None:
                    matches.append((belief, bindings))
            return matches

    def get_trace(self) -> list[str]:
        with self.lock:
            return list(self.trace)

    def prove(
        self,
        subject: str,
        predicate: str,
        object: str,
        max_depth: int = 6,
    ) -> list[str] | None:
        """Goal-directed backward search; does not mutate beliefs."""
        from kernel.prove import prove

        with self.lock:
            return prove(self, subject, predicate, object, max_depth)
