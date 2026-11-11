"""Forward-chaining inference engine: semi-naive, term-indexed, order-independent.

How it works
------------
Every belief is keyed by its (subject, predicate, object) tuple. New facts go
on an agenda. When a fact leaves the agenda, each binary rule is applied with
it in *both* premise positions, against every belief already known. So every
pair of beliefs is combined at least once (when the later of the two leaves
the agenda) however the facts arrived: one batch, one at a time, or in any
order. This is semi-naive evaluation.

Layer 1 rules only combine premises that share a term (see
docs/design/kernel-rules.md), so partners are looked up by
(predicate, term) instead of scanning every fact of the partner predicate.
Layer 2 rules (compiled skills) make no such promise and are matched
against every fact of their partner predicate.

Confidence
----------
A belief's confidence is that of its best derivation (or its given value, if
higher). When a better derivation appears, the belief is raised and goes back
on the agenda so its consequences are raised too. `evidence` counts the
distinct derivations (rule + premises) that support a belief, plus one if it
was given; derivations that use the belief itself as a premise don't count.
Both are fixed points of the facts, so they don't depend on arrival order.

Budget
------
`infer(max_iterations)` processes at most that many agenda entries. When it
stops with work left, `saturated` is False, a warning is logged, and the
next `infer()` continues. `last_run` records iterations, rule applications
and beliefs added. Measured timings are in docs/design/kernel-rules.md.
"""

from __future__ import annotations

import collections
import logging
import threading
from dataclasses import replace

from kernel.contradictions import ContradictionResolver
from kernel.facts import Belief, Derivation, Fact, Source
from kernel.foundations import (
    EXISTS, TRUE, canonical_fact, contradiction_detection, is_ambiguous, split_term,
)
from kernel.rules import BUILTIN_RULES, KERNEL_RULES_VERSION, Rule
from kernel.truth import TruthValue

log = logging.getLogger(__name__)

Key = tuple[str, str, str]
_UNLINKED = (TRUE, EXISTS)
_RAISE_EPSILON = 1e-9
# Derivations kept per belief. On a chain, a conclusion can have a derivation
# through every intermediate term, so keeping all of them grows as n^3.
# evidence stops counting at this cap, which keeps the count order-independent.
MAX_DERIVATIONS = 16
# Facts with these predicates relate rules to rules. They are processed after
# facts about things, so a budgeted run reaches conclusions about things first
# (on a 1,000-step chain, "n0 is n1000" in about 3,000 iterations rather than
# after the ~500,000 implications between the steps). A saturated run is the
# same whatever this order is.
LATER = frozenset({"implies", "subclass_of"})
# Positive predicate -> its negation, for contradiction detection.
OPPOSITE = {"is": "not_is", "instance_of": "not_instance_of"}
OPPOSITE.update({negative: positive for positive, negative in list(OPPOSITE.items())})
CLASSIFICATIONS = {"is": ("instance_of", "subclass_of"), "not_is": ("not_instance_of",)}


def key_of(fact: Fact) -> Key:
    return (fact.subject, fact.predicate, fact.object)


def _join_terms(fact: Fact) -> set[str]:
    """Terms a rule can join on: subject and object, without negation, never the reserved words."""
    return {split_term(t)[0] for t in (fact.subject, fact.object)} - set(_UNLINKED)


class InferenceEngine:
    def __init__(self):
        self.beliefs: dict[Key, Belief] = {}
        # (derivation, conclusion) in the order they were found; get_trace() renders them.
        self.trace: list[tuple[Derivation, Key]] = []
        self.resolver = ContradictionResolver()
        self.lock = threading.RLock()
        self.agenda: collections.deque[Key] = collections.deque()
        self._queued: set[Key] = set()
        self._later: collections.deque[Key] = collections.deque()
        # Beliefs that have left the agenda. A fact is joined only with these,
        # so each pair is combined once: when the later of the two is processed.
        self._done: set[Key] = set()
        self.rules: list[Rule] = list(BUILTIN_RULES)
        self._builtin = {rule.name for rule in BUILTIN_RULES}
        self._versions = {rule.name: rule.version for rule in BUILTIN_RULES}
        self._versions["contradiction_detection"] = KERNEL_RULES_VERSION
        self.rules_by_trigger: dict[str, list[Rule]] = {}
        self.rules_by_partner: dict[str, list[Rule]] = {}
        for rule in self.rules:
            self._register(rule)
        self.index: dict[str, set[Key]] = collections.defaultdict(set)
        self.term_index: dict[tuple[str, str], set[Key]] = collections.defaultdict(set)
        # False when the last infer() stopped at its budget with work left.
        self.saturated = True
        self.last_run = {"iterations": 0, "rule_applications": 0, "added": 0, "saturated": True}
        self._added: list[Fact] = []
        self._applications = 0

    # ------------------------------------------------------------ building
    def _register(self, rule: Rule) -> None:
        self.rules_by_trigger.setdefault(rule.trigger, []).append(rule)
        if rule.partner is not None:
            self.rules_by_partner.setdefault(rule.partner, []).append(rule)

    def _store(self, k: Key, belief: Belief) -> None:
        self.beliefs[k] = belief
        self.index[k[1]].add(k)
        for term in _join_terms(belief.fact):
            self.term_index[(k[1], term)].add(k)
        self._enqueue(k)

    def _enqueue(self, k: Key) -> None:
        if k not in self._queued:
            self._queued.add(k)
            (self._later if k[1] in LATER else self.agenda).append(k)

    def add_fact(self, fact: Fact) -> None:
        with self.lock:
            fact = canonical_fact(fact)
            k = key_of(fact)
            existing = self.beliefs.get(k)
            if existing is None:
                self._store(k, Belief(fact=fact, given=True))
                self._flag_contradictions(fact)
            else:
                if not existing.given:
                    existing.given = True
                    existing.evidence += 1
                # Given more than once: keep the highest confidence, whatever the order.
                existing.given_confidence = max(existing.given_confidence or 0.0, fact.confidence)
                self._raise(existing, fact.confidence)

    def add_facts(self, facts: list[Fact]) -> None:
        for f in facts:
            self.add_fact(f)

    def add_rule(self, rule: Rule) -> None:
        """Register a layer-2 rule (e.g. a compiled skill) and apply it to what is already known."""
        with self.lock:
            if any(existing.name == rule.name for existing in self.rules):
                return
            self.rules.append(rule)
            self._versions[rule.name] = rule.version
            self._register(rule)
            for k in list(self.beliefs):
                if k[1] == rule.trigger:
                    self._fire(rule, self.beliefs[k].fact, k, as_trigger=True)

    def retract(self, fact: Fact) -> None:
        """Remove a given fact and everything that depended on it."""
        with self.lock:
            k = key_of(canonical_fact(fact))
            if k not in self.beliefs:
                return
            remaining = [replace(b.fact, confidence=b.given_confidence)
                         for key, b in self.beliefs.items() if key != k and b.given]
            self.beliefs.clear()
            self.trace.clear()
            self.agenda.clear()
            self._later.clear()
            self._queued.clear()
            self._done.clear()
            self.index.clear()
            self.term_index.clear()
            self.add_facts(remaining)
            self.infer()

    # ----------------------------------------------------------- inference
    def infer(self, max_iterations: int = 10000) -> list[Fact]:
        """Run the agenda; return the beliefs this call added."""
        with self.lock:
            self._added = []
            self._applications = 0
            iterations = 0
            while (self.agenda or self._later) and iterations < max_iterations:
                k = self.agenda.popleft() if self.agenda else self._later.popleft()
                self._queued.discard(k)
                belief = self.beliefs.get(k)
                if belief is not None:
                    self._done.add(k)
                    self._process(belief.fact, k)
                iterations += 1
            self.saturated = not self._queued
            self.last_run = {"iterations": iterations, "rule_applications": self._applications,
                             "added": len(self._added), "saturated": self.saturated}
            if not self.saturated:
                log.warning(
                    "infer() stopped after %d iterations with %d facts still queued; "
                    "call infer() again to continue", iterations, len(self._queued))
            return self._added

    def _process(self, fact: Fact, k: Key) -> None:
        for rule in self.rules_by_trigger.get(fact.predicate, ()):
            self._fire(rule, fact, k, as_trigger=True)
        for rule in self.rules_by_partner.get(fact.predicate, ()):
            self._fire(rule, fact, k, as_trigger=False)
        if fact.predicate in OPPOSITE:
            self._flag_contradictions(fact)

    def _candidates(self, predicate: str, fact: Fact, shared_term: bool) -> list[Key]:
        """Processed beliefs with `predicate` that could combine with `fact`."""
        terms = _join_terms(fact)
        done = self._done
        if not shared_term or not terms:
            return [k for k in self.index.get(predicate, ()) if k in done]
        if len(terms) == 1:
            return [k for k in self.term_index.get((predicate, next(iter(terms))), ()) if k in done]
        found: set[Key] = set()
        for term in terms:
            found.update(self.term_index.get((predicate, term), ()))
        return [k for k in found if k in done]

    def _fire(self, rule: Rule, fact: Fact, k: Key, as_trigger: bool) -> None:
        if rule.partner is None:
            if as_trigger:
                self._applications += 1
                self._admit(rule.name, rule.apply(fact), (k,))
            return
        other_predicate = rule.partner if as_trigger else rule.trigger
        shared = rule.name in self._builtin
        for other_k in self._candidates(other_predicate, fact, shared):
            other = self.beliefs[other_k].fact
            self._applications += 1
            if as_trigger:
                self._admit(rule.name, rule.apply(fact, other), (k, other_k))
            else:
                self._admit(rule.name, rule.apply(other, fact), (other_k, k))

    def _admit(self, rule_name: str, outcome, premises: tuple[Key, ...]) -> None:
        if not outcome:
            return
        for result in outcome if isinstance(outcome, list) else [outcome]:
            result = canonical_fact(result)
            k = key_of(result)
            if k in premises:
                continue  # circular: a fact can't support itself
            # Same rule and same premise set = same derivation, whatever the order the rule took them in.
            if len(premises) == 2 and premises[1] < premises[0]:
                identity = (rule_name, (premises[1], premises[0]))
            else:
                identity = (rule_name, premises if len(premises) < 3 else tuple(sorted(premises)))
            belief = self.beliefs.get(k)
            if belief is not None and identity in belief.derivations:
                # The same derivation again. Only a higher confidence (a premise rose) changes anything.
                i = belief.derivations[identity]
                if result.confidence > belief.proofs[i].confidence + _RAISE_EPSILON:
                    belief.proofs[i] = replace(belief.proofs[i], confidence=result.confidence)
                    self._raise(belief, result.confidence)
                continue
            record = Derivation(rule_name, premises, result.confidence, self._versions.get(rule_name, "1"))
            if belief is None:
                # Whatever rule made it (Layer 1 or a learned skill), a conclusion is deduced;
                # the rule name says which.
                if result.source != Source.DEDUCED:
                    result = replace(result, source=Source.DEDUCED)
                belief = Belief(fact=result, given=False, evidence=1)
                belief.derivations[identity] = 0
                belief.proofs.append(record)
                self._store(k, belief)
                self._added.append(result)
                self.trace.append((record, k))
                continue
            if len(belief.derivations) < MAX_DERIVATIONS:
                belief.derivations[identity] = len(belief.proofs)
                belief.proofs.append(record)
                belief.evidence += 1
                self.trace.append((record, k))
            self._raise(belief, result.confidence)

    def _raise(self, belief: Belief, confidence: float) -> None:
        """Keep the best confidence; if it rose, revisit the belief so its consequences rise too."""
        if confidence > belief.confidence + _RAISE_EPSILON:
            belief.fact = replace(belief.fact, confidence=confidence)
            belief.truth = TruthValue(confidence, belief.truth.confidence)
            self._enqueue(key_of(belief.fact))

    def _flag_contradictions(self, fact: Fact) -> None:
        opposite = OPPOSITE.get(fact.predicate)
        if opposite is None:
            return
        other_k = (fact.subject, opposite, fact.object)
        if other_k in self.beliefs:
            k = key_of(fact)
            pair = (k, other_k) if fact.predicate in ("is", "instance_of") else (other_k, k)
            self._admit("contradiction_detection",
                        contradiction_detection(self.beliefs[pair[0]].fact, self.beliefs[pair[1]].fact), pair)

    # ------------------------------------------------------- explanations
    def explain(self, subject: str, predicate: str, object: str) -> list[tuple[Key, Derivation | None]] | None:
        """Walk a belief back to the given facts it rests on (Stage 1.4, #30).

        Returns (key, derivation) steps, inputs first: a given fact has
        derivation None, and every derived step's premises appear before it.
        Returns None if there is no such belief.

        The walk is well-founded: a belief is used only once some derivation
        of it has every premise already explained, so cycles in the
        derivation graph (a from b, b from a) can't trap it. Among the
        derivations available at each round, the most confident is used.
        """
        with self.lock:
            goal = key_of(canonical_fact(Fact(subject, predicate, object)))
            if goal not in self.beliefs:
                return None
            # Everything the goal could rest on.
            needed, stack = set(), [goal]
            while stack:
                k = stack.pop()
                if k in needed:
                    continue
                needed.add(k)
                belief = self.beliefs[k]
                if not belief.given:
                    for d in belief.proofs:
                        stack.extend(p for p in d.premises if p in self.beliefs)
            explained: dict[Key, Derivation | None] = {k: None for k in needed if self.beliefs[k].given}
            order = sorted(explained)
            while goal not in explained:
                ready = []
                for k in sorted(needed - explained.keys()):
                    usable = [d for d in self.beliefs[k].proofs if all(p in explained for p in d.premises)]
                    if usable:
                        ready.append((k, max(usable, key=lambda d: (d.confidence, d.rule))))
                if not ready:
                    return None  # unreachable: a stored belief always has a founding derivation
                for k, d in ready:
                    explained[k] = d
                    order.append(k)
            # Keep only what the goal actually uses.
            used, stack = set(), [goal]
            while stack:
                k = stack.pop()
                if k not in used:
                    used.add(k)
                    if explained[k] is not None:
                        stack.extend(explained[k].premises)
            return [(k, explained[k]) for k in order if k in used]

    def render_explanation(self, subject: str, predicate: str, object: str) -> list[str] | None:
        """explain() as text: "[given] ..." for inputs, "[rule] premises -> conclusion" for steps."""
        steps = self.explain(subject, predicate, object)
        if steps is None:
            return None
        return [f"[given] {' '.join(k)}" if d is None else d.render(k) for k, d in steps]

    # ----------------------------------------------------- ambiguous "is"
    def ambiguous(self) -> list[Fact]:
        """Given facts whose "is" could mean instance_of or subclass_of (DR3.2: never guessed).

        They still take part in the inferences that are sound under both
        readings. Use classify() once the meaning is known.
        """
        with self.lock:
            return [b.fact for b in self.beliefs.values() if b.given and is_ambiguous(b.fact)]

    def classify(self, fact: Fact, predicate: str) -> Fact:
        """Replace an ambiguous "is" / "not_is" fact with its intended predicate and return the new fact.

        "is" becomes "instance_of" or "subclass_of"; "not_is" becomes "not_instance_of".
        """
        with self.lock:
            fact = canonical_fact(fact)
            allowed = CLASSIFICATIONS.get(fact.predicate, ()) if is_ambiguous(fact) else ()
            if predicate not in allowed:
                raise ValueError(f"{fact} can't be classified as {predicate!r}; allowed: {allowed}")
            belief = self.beliefs.get(key_of(fact))
            if belief is None or not belief.given:
                raise KeyError(f"{fact} is not a given fact")
            classified = replace(belief.fact, predicate=predicate, confidence=belief.given_confidence)
            self.retract(fact)
            self.add_fact(classified)
            self.infer()
            return classified

    # ------------------------------------------------------------- queries
    def query(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        object: str | None = None,
    ) -> list[Belief]:
        with self.lock:
            if subject and predicate and object:
                belief = self.beliefs.get(key_of(canonical_fact(Fact(subject, predicate, object))))
                return [belief] if belief else []
            pool = self.index.get(predicate, ()) if predicate else self.beliefs.keys()
            results = []
            for k in pool:
                if subject and k[0] != subject:
                    continue
                if object and k[2] != object:
                    continue
                results.append(self.beliefs[k])
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
            return [record.render(k) for record, k in self.trace]

    def prove(
        self,
        subject: str,
        predicate: str,
        object: str,
        max_depth: int = 6,
    ) -> list[str] | None:
        """Goal-directed proof over the facts connected to the goal; does not mutate beliefs."""
        from kernel.prove import prove

        with self.lock:
            return prove(self, subject, predicate, object, max_depth)
