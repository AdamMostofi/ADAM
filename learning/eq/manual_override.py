"""Manual Override — user can set EQ state via natural language.

User says "this is annoying" or "let's go" and ADAM adapts.
"""
from __future__ import annotations

from learning.eq import lexicon
from learning.eq.user_state import UserState, GoalStatus, EmotionalTone, Agency

# Matched on word boundaries (Stage 1.7, #37): "unhappy" is not "happy", "whatever" is
# not "hate". Only explicit, un-negated emotion words override the appraisal; a negated
# one ("not happy") is left to the appraiser, which weighs it with everything else.
NEGATIVE_SIGNALS = ["annoying", "frustrated", "angry", "upset", "hate", "stupid", "terrible", "awful", "unhappy"]
POSITIVE_SIGNALS = ["let's go", "awesome", "excited", "love", "amazing", "great", "perfect", "happy"]


class ManualOverride:
    def __init__(self):
        self.override_active: bool = False
        self.override_state: UserState | None = None

    def detect_override(self, user_input: str) -> UserState | None:
        pos = lexicon.explicit(user_input, POSITIVE_SIGNALS)
        neg = lexicon.explicit(user_input, NEGATIVE_SIGNALS)
        if neg > pos:
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
        if pos > neg:
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
