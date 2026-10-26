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
from interface.mouth import Mouth


class ADAMCore:
    def __init__(self, db_path: str = "adam_memory.db", lance_path: str = "adam_vectors.lance", mouth=None):
        self.memory = MemorySystem(db_path, lance_path)
        self.learning = LearningEngine(memory_system=self.memory)
        self.eq = EQEngine(db_path)
        self.engine = self.memory.engine
        self.ear = Ear()
        self.mouth = mouth if mouth is not None else Mouth()

    def chat(self, message: str, mode: str = "full") -> dict:
        intent = self.ear.listen(message)
        user_state, params = self.eq.process_input(message)

        if mode == "simple":
            memories = self.memory.recall(message, limit=5)
            context_text = "\n".join(f"{f.subject} {f.predicate} {f.object}" for f in memories)
            core_response = self._format_response(message, params, context_text)
        else:
            relevant = self.memory.recall(message, limit=5)
            for fact in relevant:
                self.engine.add_fact(fact)
            inferred = self.engine.infer()
            for fact in inferred:
                self.memory.store(fact)
            memories = self.memory.recall(message, limit=10)
            context_text = "\n".join(f"{f.subject} {f.predicate} {f.object}" for f in memories)
            core_response = self._format_response(message, params, context_text)

        response = self.mouth.format_response(core_response, {
            "warmth": params.warmth,
            "depth": params.depth,
            "tone": user_state.emotional_tone.value,
        })

        self.eq.tracker.update(user_state)
        self.eq.baseline.record_interaction(user_state)
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
            "memories_used": len(memories) if 'memories' in dir() else 0,
        }

    def _format_response(self, message: str, params, context: str) -> str:
        parts = []
        if params.empathetic_opening:
            parts.append("I understand this might be frustrating.")
        parts.append(f"Based on what I know: {message}")
        if params.encouraging_closing:
            parts.append("Let's keep going!")
        return " ".join(parts)

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
        graph = self.memory.graph
        nodes = {}
        for u, v, d in graph.get_all_edges():
            source = d.get("source", "user")
            nodes.setdefault(u, {"id": u, "label": u, "source": source})
            nodes.setdefault(v, {"id": v, "label": v, "source": source})
        edges = [
            {"from": u, "to": v, "label": d.get("predicate", "")}
            for u, v, d in graph.get_all_edges()
        ]
        return {"nodes": list(nodes.values()), "edges": edges}

    def get_skills(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "domain": s.domain,
                "confidence": s.confidence,
                "premises": s.premises,
                "conclusion": s.conclusion,
            }
            for s in self.learning.skill_compiler.skills.values()
        ]

    def get_stats(self) -> dict:
        by_source = self.memory.exact.count_by_source()
        return {
            "facts": self.memory.count(),
            "skills": len(self.learning.skill_compiler.skills),
            "nodes": len(self.memory.graph.get_all_nodes()),
            "edges": len(self.memory.graph.get_all_edges()),
            "baseline": self.eq.get_baseline(),
            "mood_shift": self.eq.detect_mood_shift(),
            "by_source": by_source,
            "deduced": by_source.get("deduced", 0),
            "contradictions": len(self.engine.resolver.get_contradictions()),
            "trace_steps": len(self.engine.trace),
        }

    def save(self, path: str) -> None:
        self.memory.save(path)
        self.eq.save()

    def load(self, path: str) -> None:
        self.memory = MemorySystem.load(path)
        self.learning.memory = self.memory
        self.engine = self.memory.engine
