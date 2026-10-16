"""Manual Override — user can set EQ state via natural language.

User says "this is annoying" or "let's go" and ADAM adapts.
"""
from __future__ import annotations

from learning.eq.user_state import UserState, GoalStatus, EmotionalTone, Agency


class ManualOverride:
    def __init__(self):
        self.override_active: bool = False
        self.override_state: UserState | None = None

    def detect_override(self, user_input: str) -> UserState | None:
        text_lower = user_input.lower()
        negative_signals = ["annoying", "frustrated", "angry", "upset", "hate", "stupid", "terrible", "awful"]
        positive_signals = ["let's go", "awesome", "excited", "love", "amazing", "great", "perfect", "happy"]
        if any(signal in text_lower for signal in negative_signals):
            self.override_active = True
            self.override_state = UserState(
                goal_status=GoalStatus.BLOCKED,
                emotional_tone=EmotionalTone.NEGATIVE,
                engagement=0.3,
                agency=Agency.SELF,
                confidence=0.2,
                novelty=0.5,
                goal_relevance=0.8,
                goal_congruence=0.2,
                coping=0.2,
            )
            return self.override_state
        if any(signal in text_lower for signal in positive_signals):
            self.override_active = True
            self.override_state = UserState(
                goal_status=GoalStatus.ACHIEVED,
                emotional_tone=EmotionalTone.POSITIVE,
                engagement=0.9,
                agency=Agency.SELF,
                confidence=0.9,
                novelty=0.7,
                goal_relevance=0.9,
                goal_congruence=0.9,
                coping=0.9,
            )
            return self.override_state
        self.override_active = False
        self.override_state = None
        return None

    def clear_override(self) -> None:
        self.override_active = False
        self.override_state = None

    def is_override_active(self) -> bool:
        return self.override_active

    def get_override_state(self) -> UserState | None:
        return self.override_state
