"""ADAMCore — facade wiring all 4 subsystems into a single API."""
from __future__ import annotations

import os
import tempfile

from kernel.engine import InferenceEngine
from kernel.facts import Fact, Source
from memory.system import MemorySystem
from learning.engine import LearningEngine
from learning.eq.engine import EQEngine


class ADAMCore:
    def __init__(self, db_path: str = "adam_memory.db", lance_path: str = "adam_vectors.lance"):
        self.memory = MemorySystem(db_path, lance_path)
        self.learning = LearningEngine(memory_system=self.memory)
        self.eq = EQEngine(db_path)
        self.engine = self.memory.engine

    def chat(self, message: str, mode: str = "full") -> dict:
        user_state, params = self.eq.process_input(message)

        if mode == "simple":
            memories = self.memory.recall(message, limit=5)
            context_text = "\n".join(f"{f.subject} {f.predicate} {f.object}" for f in memories)
            response = self._format_response(message, params, context_text)
        else:
            relevant = self.memory.recall(message, limit=5)
            for fact in relevant:
                self.engine.add_fact(fact)
            inferred = self.engine.infer()
            for fact in inferred:
                self.memory.store(fact)
            memories = self.memory.recall(message, limit=10)
            context_text = "\n".join(f"{f.subject} {f.predicate} {f.object}" for f in memories)
            response = self._format_response(message, params, context_text)

        self.eq.tracker.update(user_state)
        self.eq.baseline.record_interaction(user_state)
        self.eq.save()

        return {
            "response": response,
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
                "id": r["id"],
            }
            for r in results
        ]

    def get_graph_data(self) -> dict:
        graph = self.memory.graph
        nodes = []
        seen = set()
        for u, v, d in graph.get_all_edges():
            if u not in seen:
                nodes.append({"id": u, "label": u})
                seen.add(u)
            if v not in seen:
                nodes.append({"id": v, "label": v})
                seen.add(v)
        edges = [
            {"from": u, "to": v, "label": d.get("predicate", "")}
            for u, v, d in graph.get_all_edges()
        ]
        return {"nodes": nodes, "edges": edges}

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
        return {
            "facts": self.memory.count(),
            "skills": len(self.learning.skill_compiler.skills),
            "nodes": len(self.memory.graph.get_all_nodes()),
            "edges": len(self.memory.graph.get_all_edges()),
            "baseline": self.eq.get_baseline(),
            "mood_shift": self.eq.detect_mood_shift(),
        }

    def save(self, path: str) -> None:
        self.memory.save(path)
        self.eq.save()

    def load(self, path: str) -> None:
        self.memory = MemorySystem.load(path)
        self.learning.memory = self.memory
        self.engine = self.memory.engine
