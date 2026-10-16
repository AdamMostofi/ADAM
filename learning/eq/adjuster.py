"""Response Adjuster — adapts response style based on user state.

Based on Chain-of-Emotion architecture (2024) and
educational assistant adaptation research (2025).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from learning.eq.user_state import UserState, GoalStatus, EmotionalTone


@dataclass
class ResponseParams:
    warmth: str = "medium"
    directness: str = "direct"
    depth: str = "detailed"
    caution_flag: bool = False
    verification_steps: list[str] = field(default_factory=list)
    empathetic_opening: bool = False
    encouraging_closing: bool = False


class ResponseAdjuster:
    def adjust(self, user_state: UserState, base_response: str = "") -> tuple[str, ResponseParams]:
        if user_state.goal_status == GoalStatus.ACHIEVED:
            return self._celebrate(base_response), ResponseParams(
                warmth="high", directness="direct", depth="summary",
                caution_flag=False, encouraging_closing=True,
            )
        if user_state.goal_status == GoalStatus.BLOCKED:
            return self._encourage(base_response), ResponseParams(
                warmth="high", directness="gentle", depth="detailed",
                caution_flag=True, verification_steps=["verify", "simplify"],
                empathetic_opening=True, encouraging_closing=True,
            )
        if user_state.goal_status == GoalStatus.THREATENED:
            return self._empathize(base_response), ResponseParams(
                warmth="very high", directness="very gentle", depth="concise",
                caution_flag=True, verification_steps=["empathize", "validate", "simplify"],
                empathetic_opening=True, encouraging_closing=True,
            )
        if user_state.emotional_tone == EmotionalTone.NEGATIVE:
            return self._empathize(base_response), ResponseParams(
                warmth="very high", directness="very gentle", depth="concise",
                caution_flag=True, verification_steps=["empathize", "validate"],
                empathetic_opening=True,
            )
        if user_state.emotional_tone == EmotionalTone.POSITIVE:
            return self._encourage(base_response), ResponseParams(
                warmth="high", directness="direct", depth="detailed",
                caution_flag=False, encouraging_closing=True,
            )
        return base_response, ResponseParams()

    def _celebrate(self, response: str) -> str:
        if not response:
            return "Great! Let's keep the momentum going."
        return f"Great! {response}"

    def _encourage(self, response: str) -> str:
        if not response:
            return "You're making good progress. Keep going!"
        return f"You're making good progress. {response}"

    def _empathize(self, response: str) -> str:
        if not response:
            return "I understand this is frustrating. Let's work through it together."
        return f"I understand this is frustrating. {response}"
