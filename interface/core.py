"""ADAMCore — facade wiring all 4 subsystems into a single API."""
from __future__ import annotations

import os
import tempfile

from kernel.engine import InferenceEngine
from kernel.facts import Fact, Source
from memory.system import MemorySystem
from learning.engine import LearningEngine
from learning.eq.engine import EQEngine
from interface.ear import Ear
from interface.evidence import Answerer
from interface.mouth import Mouth, small_talk
from memory.source_library import SourceError

# Agenda entries one chat turn may process (Stage 1.2, #28). Inference is
# incremental, so a turn only pays for consequences of what it added; work
# left over stays queued and continues on the next turn.
CHAT_INFERENCE_BUDGET = 2000


class ADAMCore:
    def __init__(self, db_path: str = "adam_memory.db", lance_path: str = "adam_vectors.db", mouth=None, ear=None):
        self.memory = MemorySystem(db_path, lance_path)
        self.learning = LearningEngine(memory_system=self.memory)
        self.eq = EQEngine(db_path)
        self.engine = self.memory.engine
        for rule in self.learning.skill_compiler.rules():
            self.engine.add_rule(rule)
        # Startup stays read-only (Stage 1.6, #36): conclusions of the skills just registered
        # are inferred in memory and stored the next time ADAM writes.
        self.engine.infer()
        self.ear = ear if ear is not None else Ear()
        self.mouth = mouth if mouth is not None else Mouth()

    def chat(self, message: str, mode: str = "full") -> dict:
        intent = self.ear.listen(message)
        user_state, params = self.eq.process_input(message)

        if mode == "simple":
            memories = self.memory.recall(message, limit=5)
        else:
            relevant = self.memory.recall(message, limit=5)
            for fact in relevant:
                # A recalled derived fact is already a consequence in the engine; giving it again
                # would make it outlive its premises (Stage 1.6, #36).
                if fact.source != Source.DEDUCED:
                    self.engine.add_fact(fact)
            # Store, with their derivations and in one transaction (Stage 1.4), every belief the
            # store doesn't have yet: this turn's conclusions and any found at startup (Stage 1.6).
            self.memory.settle(self.engine, max_iterations=CHAT_INFERENCE_BUDGET)
            memories = self.memory.recall(message, limit=10)

        # Stage 4.3 (#34): the reply comes from evidence. Facts are worded from proofs, passages are quoted,
        # and the Mouth speaks only where nothing factual is at stake (interface/evidence.py).
        answer = Answerer(self.engine, self._library(), self.mouth, small_talk).answer(message, {
            "warmth": params.warmth,
            "depth": params.depth,
            "tone": user_state.emotional_tone.value,
        })
        response = answer.text

        # process_input() already recorded this turn in the tracker and the baseline (Stage 1.7, #37).
        self.eq.save()

        return {
            "response": response,
            "intent": {
                "action": intent.action,
                "topic": intent.topic,
                "sentiment": intent.sentiment,
            },
            "state": {
                "goal_status": user_state.goal_status.value,
                "emotional_tone": user_state.emotional_tone.value,
                "engagement": user_state.engagement,
                "confidence": user_state.confidence,
            },
            "params": {
                "warmth": params.warmth,
                "directness": params.directness,
                "depth": params.depth,
                "caution_flag": params.caution_flag,
                "empathetic_opening": params.empathetic_opening,
                "encouraging_closing": params.encouraging_closing,
            },
            "memories_used": len(memories),
            "answer_source": answer.answer_source,
            "evidence": answer.evidence,
        }

    def _library(self):
        """The source library, or None when the store keeps no records or the library can't open."""
        try:
            return self.memory.source_library()
        except SourceError:
            return None

    def add_fact(self, subject: str, predicate: str, obj: str) -> int:
        fact = Fact(
            subject=subject,
            predicate=predicate,
            object=obj,
            confidence=1.0,
            source=Source.USER,
            timestamp=__import__('time').time(),
        )
        self.engine.add_fact(fact)
        return self.memory.store(fact)

    def conflicts(self) -> list[dict]:
        """Every recorded conflict and how it was resolved (Stage 1.5, #31)."""
        return [c.to_record() for c in self.engine.conflicts()]

    def ambiguous_facts(self) -> list[dict]:
        """Given facts whose "is" could mean instance_of or subclass_of (Stage 1.3, #29)."""
        return [{"subject": f.subject, "predicate": f.predicate, "object": f.object}
                for f in self.engine.ambiguous()]

    def classify_fact(self, subject: str, predicate: str, obj: str, meaning: str) -> dict:
        """Resolve an ambiguous fact to instance_of / subclass_of / not_instance_of.

        The engine replaces it, the classified fact is stored, and the original
        row is kept but marked superseded, so a restart doesn't restore it.
        """
        original = Fact(subject, predicate, obj)
        classified = self.engine.classify(original, meaning)
        new_id = self.memory.store(classified)
        # The original row is kept but marked, so a restart doesn't bring the ambiguous fact back.
        self.memory.supersede(original, new_id)
        self.memory.settle(self.engine)  # store what the classification lets ADAM conclude
        return {"subject": classified.subject, "predicate": classified.predicate, "object": classified.object}

    def query_knowledge(self, query: str) -> list[dict]:
        results = self.memory.search(query)
        return [
            {
                "subject": r["subject"],
                "predicate": r["predicate"],
                "object": r["object"],
                "confidence": r["confidence"],
                "source": r.get("source", "user"),
                "id": r["id"],
            }
            for r in results
        ]

    def get_graph_data(self) -> dict:
        graph_edges = self.memory.graph_edges()
        nodes = {}
        for u, v, d in graph_edges:
            source = d.get("source", "user")
            nodes.setdefault(u, {"id": u, "label": u, "source": source})
            nodes.setdefault(v, {"id": v, "label": v, "source": source})
        edges = [
            {"from": u, "to": v, "label": d.get("predicate", "")}
            for u, v, d in graph_edges
        ]
        return {"nodes": list(nodes.values()), "edges": edges}

    def get_skills(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "domain": s.domain,
                "confidence": s.confidence,
                "fitness": s.fitness,
                "attempts": s.attempts,
                "successes": s.successes,
                "premises": s.premises,
                "conclusion": s.conclusion,
            }
            for s in self.learning.skill_compiler.skills.values()
        ]

    def get_stats(self) -> dict:
        memory = self.memory.stats()
        by_source = memory["by_source"]
        return {
            "facts": memory["facts"],
            "skills": len(self.learning.skill_compiler.skills),
            "nodes": memory["nodes"],
            "edges": memory["edges"],
            "store": memory["store"],
            "baseline": self.eq.get_baseline(),
            "mood_shift": self.eq.detect_mood_shift(),
            "by_source": by_source,
            "deduced": by_source.get("deduced", 0),
            "contradictions": len(self.engine.conflicts()),
            "startup": self.memory.startup,
            "trace_steps": len(self.engine.trace),
        }

    def save(self, path: str) -> None:
        self.memory.save(path)
        self.eq.save()

    def load(self, path: str) -> None:
        self.memory = MemorySystem.load(path)
        self.learning.memory = self.memory
        self.engine = self.memory.engine
        for rule in self.learning.skill_compiler.rules():
            self.engine.add_rule(rule)
        self.engine.infer()
