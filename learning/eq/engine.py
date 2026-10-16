"""EQ Engine — main API for emotional intelligence.

Wraps user state tracking, cognitive appraisal, response adjustment,
baseline learning, persistence, and manual override.
"""
from __future__ import annotations

import os

from learning.eq.user_state import UserState, UserStateTracker, GoalStatus, EmotionalTone
from learning.eq.appraiser import CognitiveAppraiser
from learning.eq.adjuster import ResponseAdjuster, ResponseParams
from learning.eq.baseline import BaselineLearner
from learning.eq.manual_override import ManualOverride
from learning.eq.persistence import save_eq_state, load_eq_state


class EQEngine:
    def __init__(self, db_path: str = "adam_memory.db"):
        self.tracker = UserStateTracker()
        self.appraiser = CognitiveAppraiser()
        self.adjuster = ResponseAdjuster()
        self.baseline = BaselineLearner()
        self.manual = ManualOverride()
        self.db_path = db_path
        self._load()

    def process_input(self, user_input: str, context: dict | None = None) -> tuple[UserState, ResponseParams]:
        override = self.manual.detect_override(user_input)
        if override:
            state = override
        else:
            state = self.appraiser.appraise(user_input, context)
        self.tracker.update(state)
        self.baseline.record_interaction(state)
        _, params = self.adjuster.adjust(state)
        return state, params

    def get_state(self) -> UserState:
        return self.tracker.get_state()

    def get_baseline(self) -> float:
        return self.baseline.get_baseline()

    def detect_mood_shift(self) -> bool:
        return self.baseline.detect_mood_shift()

    def should_adapt_immediately(self, state: UserState) -> bool:
        if state.emotional_tone == EmotionalTone.NEGATIVE and state.confidence < 0.3:
            return True
        if state.goal_status == GoalStatus.ACHIEVED and state.confidence > 0.9:
            return True
        if self.baseline.detect_mood_shift():
            return True
        return False

    def add_goal(self, goal: str) -> None:
        self.appraiser.add_goal(goal)

    def clear_override(self) -> None:
        self.manual.clear_override()

    def save(self) -> None:
        save_eq_state(self.db_path, self.baseline, self.tracker.get_state())

    def _load(self) -> None:
        result = load_eq_state(self.db_path)
        if result:
            baseline, state = result
            self.baseline = baseline
            self.tracker.update(state)
