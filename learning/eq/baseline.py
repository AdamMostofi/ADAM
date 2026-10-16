"""Baseline Learner — tracks user's emotional baseline and preferences over time.

Based on emotional trajectory modeling (Markov process) and
educational assistant adaptation research.
"""
from __future__ import annotations

from collections import deque

from learning.eq.user_state import UserState, EmotionalTone


class BaselineLearner:
    def __init__(self, history_size: int = 10):
        self.history_size = history_size
        self.interaction_history: deque[dict] = deque(maxlen=history_size)
        self.emotional_baseline: float = 0.5
        self.topic_counts: dict[str, int] = {}
        self.style_counts: dict[str, int] = {"direct": 0, "exploratory": 0}

    def record_interaction(self, state: UserState, topic: str = "", style: str = "") -> None:
        self.interaction_history.append({
            "emotional_tone": state.emotional_tone.value,
            "engagement": state.engagement,
            "goal_status": state.goal_status.value,
        })
        if topic:
            self.topic_counts[topic] = self.topic_counts.get(topic, 0) + 1
        if style:
            self.style_counts[style] = self.style_counts.get(style, 0) + 1
        self._update_baseline()

    def _update_baseline(self) -> None:
        if not self.interaction_history:
            return
        tones = [h["emotional_tone"] for h in self.interaction_history]
        positive_count = sum(1 for t in tones if t == "positive")
        self.emotional_baseline = positive_count / len(tones)

    def detect_mood_shift(self, window: int = 3) -> bool:
        if len(self.interaction_history) < window:
            return False
        recent = list(self.interaction_history)[-window:]
        return all(h["emotional_tone"] == "negative" for h in recent)

    def get_dominant_topic(self) -> str | None:
        if not self.topic_counts:
            return None
        return max(self.topic_counts, key=lambda k: self.topic_counts[k])

    def get_preferred_style(self) -> str:
        if not self.style_counts:
            return "direct"
        return max(self.style_counts, key=lambda k: self.style_counts[k])

    def get_baseline(self) -> float:
        return self.emotional_baseline

    def get_history_size(self) -> int:
        return len(self.interaction_history)

    def to_dict(self) -> dict:
        return {
            "emotional_baseline": self.emotional_baseline,
            "topic_counts": dict(self.topic_counts),
            "style_counts": dict(self.style_counts),
            "history_size": len(self.interaction_history),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BaselineLearner":
        learner = cls()
        learner.emotional_baseline = data.get("emotional_baseline", 0.5)
        learner.topic_counts = data.get("topic_counts", {})
        learner.style_counts = data.get("style_counts", {"direct": 0, "exploratory": 0})
        return learner
