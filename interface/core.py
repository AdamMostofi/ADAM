"""ADAMCore — facade wiring all 4 subsystems into a single API."""
from __future__ import annotations

import collections
import hashlib
import os
import tempfile
import uuid

from kernel.engine import InferenceEngine
from kernel.facts import Fact, Source
from memory.system import MemorySystem
from learning.engine import LearningEngine
from learning.eq.frustration import FrustrationReader
from interface.ear import Ear
from interface.evidence import Answerer
from interface.mouth import Mouth, small_talk
from memory.source_library import SourceError
from memory.trace_log import node as trace_node, render as render_trace, valid_conversation

# Agenda entries one chat turn may process (Stage 1.2, #28). Inference is
# incremental, so a turn only pays for consequences of what it added; work
# left over stays queued and continues on the next turn.
CHAT_INFERENCE_BUDGET = 2000

# What the Mouth is told about tone: nothing (Stage 4.4, #77). EQ's parameters changed nothing visible.
NEUTRAL_PARAMS = {"warmth": "medium", "depth": "detailed", "tone": "neutral"}
SNIPPET_CHARS = 280


def citations(evidence: list[dict]) -> list[dict]:
    """Exact citations for the passages in a reply's evidence (Stage 4.5, #25).

    Each one names its source (key and name), the passage's ordinal, its character offsets `start` and `end`
    in the source's kept text, its SHA-256, and a snippet. The snippet is the passage's text, cut at
    SNIPPET_CHARS characters when longer, with `truncated` saying so; the cut never changes a character, so
    the snippet is always the start of text[start:end].
    """
    out = []
    for e in evidence:
        if e.get("type") != "passage":
            continue
        text = e["text"]
        out.append({"source": e["source"], "name": e["name"], "ordinal": e["ordinal"], "start": e["start"],
                    "end": e["end"], "sha256": e["sha256"], "snippet": text[:SNIPPET_CHARS],
                    "truncated": len(text) > SNIPPET_CHARS})
    return out


LEGACY_PARAMS = {"warmth": "medium", "directness": "direct", "depth": "detailed", "caution_flag": False,
                 "empathetic_opening": False, "encouraging_closing": False}


class ADAMCore:
    def __init__(self, db_path: str = "adam_memory.db", lance_path: str = "adam_vectors.db", mouth=None, ear=None):
        self.memory = MemorySystem(db_path, lance_path)
        self.learning = LearningEngine(memory_system=self.memory)
        # EQ is one signal since Stage 4.4 (#77): is the user frustrated? Per conversation, never saved.
        self.frustration = FrustrationReader()
        self._readers: collections.OrderedDict[str, FrustrationReader] = collections.OrderedDict()
        # The conversation a turn belongs to, for its thought trace (Stage 4.6): one per run unless the caller
        # (the web chat) names its own.
        self.conversation_id = "run-" + uuid.uuid4().hex[:16]
        self.engine = self.memory.engine
        for rule in self.learning.skill_compiler.rules():
            self.engine.add_rule(rule)
        # Startup stays read-only (Stage 1.6, #36): conclusions of the skills just registered
        # are inferred in memory and stored the next time ADAM writes.
        self.engine.infer()
        self.ear = ear if ear is not None else Ear()
        self.mouth = mouth if mouth is not None else Mouth()

    def chat(self, message: str, mode: str = "full", conversation: str | None = None) -> dict:
        conversation = conversation if valid_conversation(conversation) else self.conversation_id
        intent = self.ear.listen(message)
        reading = self._reader(conversation).read(message)
        stored = 0

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
            stored = self.memory.settle(self.engine, max_iterations=CHAT_INFERENCE_BUDGET)
            memories = self.memory.recall(message, limit=10)

        # Stage 4.3 (#34): the reply comes from evidence. Facts are worded from proofs, passages are quoted,
        # and the Mouth speaks only where nothing factual is at stake (interface/evidence.py).
        answer = Answerer(self.engine, self._library(), self.mouth, small_talk).answer(
            message, NEUTRAL_PARAMS, frustrated=reading.frustrated)
        response = answer.text
        cited = citations(answer.evidence)
        trace_id = self.memory.trace_log().record(conversation, self._trace_nodes(
            message, mode, reading, memories, stored, answer, cited))

        return {
            "response": response,
            "intent": {
                "action": intent.action,
                "topic": intent.topic,
                "sentiment": intent.sentiment,
            },
            # Kept for /api/chat clients (Stage 4.3 kept every key). Since Stage 4.4 they come from the frustration
            # signal: the tone is "negative" for a troubled turn, else "neutral", and the parameters are fixed.
            "state": {
                "goal_status": "unknown",
                "emotional_tone": "negative" if reading.troubled else "neutral",
                "engagement": 0.5,
                "confidence": 0.5,
            },
            "params": dict(LEGACY_PARAMS),
            "frustration": reading.to_dict(),
            "memories_used": len(memories),
            "answer_source": answer.answer_source,
            "evidence": answer.evidence,
            # Stage 4.5 (#25, D4.1): the passages the reply quotes, as exact citations. Empty unless a passage
            # answered: proofs are in `evidence`.
            "citations": cited,
            # Stage 4.6 (#35): this turn's thought trace; read it at /api/traces/<trace_id>.
            "trace_id": trace_id,
            "conversation": conversation,
        }

    def read_trace(self, trace_id: str) -> dict | None:
        """A turn's trace with its English rendering, which is generated here and never stored (Stage 4.6)."""
        if not isinstance(trace_id, str) or not trace_id.isalnum() or len(trace_id) > 64:
            return None
        trace = self.memory.trace_log().get(trace_id)
        if trace is None:
            return None
        return {**trace, "text": render_trace(trace)}

    def _reader(self, conversation: str) -> FrustrationReader:
        """The frustration reader for a conversation (the run's own, or one the web chat names)."""
        if conversation == self.conversation_id:
            return self.frustration
        reader = self._readers.pop(conversation, None) or FrustrationReader()
        self._readers[conversation] = reader
        while len(self._readers) > 100:
            self._readers.popitem(last=False)
        return reader

    def _trace_nodes(self, message, mode, reading, memories, stored, answer, cited) -> list[dict]:
        """The typed nodes of one turn (Stage 4.6): data only; English is rendered from them on request."""
        proofs = []
        for e in answer.evidence:
            if e.get("type") != "proof":
                continue
            key = tuple(e["key"])
            belief = self.engine.beliefs.get(key)
            proofs.append({"claim": e["claim"], "key": list(key), "steps": e["steps"], "origins": e["origins"],
                           "confidence": round(belief.confidence, 4) if belief else None,
                           **self.memory.fact_link(*key)})
        confidences = [p["confidence"] for p in proofs if p["confidence"] is not None]
        return [
            trace_node("PERCEIVE", {"message": message},
                       {"route": answer.route, "troubled": reading.troubled, "frustrated": reading.frustrated,
                        "cues": reading.cues}, None, ["user"]),
            trace_node("RECALL", {"query": message, "mode": mode},
                       {"facts": [str(f) for f in memories][:20], "facts_total": len(memories),
                        "library_searched": answer.library_searched,
                        "passages": [c["source"] + "#" + str(c["ordinal"]) for c in cited]},
                       None, [f"store:{self.memory.backend}"] + (["source library"] if answer.library_searched else [])),
            trace_node("INFER", {"mode": mode, "budget": CHAT_INFERENCE_BUDGET if mode != "simple" else 0},
                       {"ran": mode != "simple", "stored": stored, "proofs": proofs},
                       min(confidences) if confidences else None, sorted({s["rule"] for p in proofs for s in p["steps"]})),
            trace_node("ANSWER", {"route": answer.route},
                       {"answer_source": answer.answer_source, "response_chars": len(answer.text),
                        "response_sha256": hashlib.sha256(answer.text.encode()).hexdigest(),
                        "citations": [{k: c[k] for k in ("source", "name", "ordinal", "start", "end", "sha256")}
                                      for c in cited]},
                       None, [answer.answer_source]),
        ]

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
            "frustration": self.frustration.level(),
            "frustrated": self.frustration.frustrated(),
            "by_source": by_source,
            "deduced": by_source.get("deduced", 0),
            "contradictions": len(self.engine.conflicts()),
            "startup": self.memory.startup,
            "trace_steps": len(self.engine.trace),
        }

    def save(self, path: str) -> None:
        self.memory.save(path)

    def load(self, path: str) -> None:
        self.memory = MemorySystem.load(path)
        self.learning.memory = self.memory
        self.engine = self.memory.engine
        for rule in self.learning.skill_compiler.rules():
            self.engine.add_rule(rule)
        self.engine.infer()
