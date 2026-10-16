"""User State Tracker — tracks user's emotional and cognitive state.

Based on Scherer's Component Process Model (CPM).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class GoalStatus(Enum):
    ACHIEVED = "achieved"
    PROGRESSING = "progressing"
    BLOCKED = "blocked"
    THREATENED = "threatened"
    UNKNOWN = "unknown"


class EmotionalTone(Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class Agency(Enum):
    SELF = "self"
    OTHER = "other"
    CIRCUMSTANCE = "circumstance"


@dataclass
class UserState:
    goal_status: GoalStatus = GoalStatus.UNKNOWN
    emotional_tone: EmotionalTone = EmotionalTone.NEUTRAL
    engagement: float = 0.5
    knowledge_level: str = "beginner"
    agency: Agency = Agency.CIRCUMSTANCE
    confidence: float = 0.5
    novelty: float = 0.5
    goal_relevance: float = 0.5
    goal_congruence: float = 0.5
    coping: float = 0.5

    def to_dict(self) -> dict:
        return {
            "goal_status": self.goal_status.value,
            "emotional_tone": self.emotional_tone.value,
            "engagement": self.engagement,
            "knowledge_level": self.knowledge_level,
            "agency": self.agency.value,
            "confidence": self.confidence,
            "novelty": self.novelty,
            "goal_relevance": self.goal_relevance,
            "goal_congruence": self.goal_congruence,
            "coping": self.coping,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserState":
        return cls(
            goal_status=GoalStatus(data.get("goal_status", "unknown")),
            emotional_tone=EmotionalTone(data.get("emotional_tone", "neutral")),
            engagement=data.get("engagement", 0.5),
            knowledge_level=data.get("knowledge_level", "beginner"),
            agency=Agency(data.get("agency", "circumstance")),
            confidence=data.get("confidence", 0.5),
            novelty=data.get("novelty", 0.5),
            goal_relevance=data.get("goal_relevance", 0.5),
            goal_congruence=data.get("goal_congruence", 0.5),
            coping=data.get("coping", 0.5),
        )


class UserStateTracker:
    def __init__(self):
        self.current_state = UserState()
        self.state_history: list[UserState] = []
        self.max_history = 100

    def update(self, state: UserState) -> None:
        self.state_history.append(self.current_state)
        if len(self.state_history) > self.max_history:
            self.state_history.pop(0)
        self.current_state = state

    def get_state(self) -> UserState:
        return self.current_state

    def get_history(self) -> list[UserState]:
        return list(self.state_history)

    def detect_mood_shift(self, window: int = 3) -> bool:
        recent = [self.current_state] + self.state_history[-window:]
        if len(recent) < window:
            return False
        return all(s.emotional_tone == EmotionalTone.NEGATIVE for s in recent[-window:])

    def get_average_engagement(self, window: int = 5) -> float:
        if not self.state_history:
            return self.current_state.engagement
        recent = self.state_history[-window:]
        return sum(s.engagement for s in recent) / len(recent)
