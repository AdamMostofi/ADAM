"""Cognitive Appraiser — primary, secondary, and reappraisal.

Based on Cognitive Appraisal Theory (Lazarus & Folkman) and
Scherer's Component Process Model (CPM).
"""
from __future__ import annotations

from learning.eq.user_state import UserState, GoalStatus, EmotionalTone, Agency


class CognitiveAppraiser:
    def __init__(self):
        self.user_goals: list[str] = []
        self.interaction_count: int = 0

    def add_goal(self, goal: str) -> None:
        if goal not in self.user_goals:
            self.user_goals.append(goal)

    def appraise(self, user_input: str, context: dict | None = None) -> UserState:
        self.interaction_count += 1
        novelty = self._assess_novelty(user_input)
        relevance = self._assess_relevance(user_input)
        congruence = self._assess_congruence(user_input, context)
        coping = self._assess_coping(user_input, context)
        agency = self._assess_agency(user_input)
        tone = self._determine_tone(congruence, coping)
        goal_status = self._determine_goal_status(congruence, coping)
        engagement = self._assess_engagement(user_input)
        return UserState(
            goal_status=goal_status,
            emotional_tone=tone,
            engagement=engagement,
            agency=agency,
            confidence=coping,
            novelty=novelty,
            goal_relevance=relevance,
            goal_congruence=congruence,
            coping=coping,
        )

    def _assess_novelty(self, text: str) -> float:
        text_lower = text.lower()
        novel_indicators = ["new", "first time", "never", "what is", "how do"]
        familiar_indicators = ["again", "still", "another", "more", "continue"]
        novel_count = sum(1 for w in novel_indicators if w in text_lower)
        familiar_count = sum(1 for w in familiar_indicators if w in text_lower)
        total = novel_count + familiar_count
        if total == 0:
            return 0.5
        return novel_count / total

    def _assess_relevance(self, text: str) -> float:
        text_lower = text.lower()
        if not self.user_goals:
            return 0.5
        relevant = sum(1 for g in self.user_goals if g.lower() in text_lower)
        return min(1.0, relevant / max(len(self.user_goals), 1))

    def _assess_congruence(self, text: str, context: dict | None) -> float:
        text_lower = text.lower()
        positive = ["yes", "correct", "right", "great", "perfect", "thanks", "worked", "solved"]
        negative = ["no", "wrong", "error", "failed", "doesn't work", "broken", "issue", "frustrating", "frustrated", "annoying", "angry"]
        pos_count = sum(1 for w in positive if w in text_lower)
        neg_count = sum(1 for w in negative if w in text_lower)
        total = pos_count + neg_count
        if total == 0:
            return 0.5
        return pos_count / total

    def _assess_coping(self, text: str, context: dict | None) -> float:
        text_lower = text.lower()
        high_coping = ["i can", "i know", "i understand", "easy", "simple", "clear"]
        low_coping = ["i can't", "i don't know", "don't understand", "confusing", "hard", "difficult", "help", "frustrating", "frustrated"]
        high_count = sum(1 for w in high_coping if w in text_lower)
        low_count = sum(1 for w in low_coping if w in text_lower)
        total = high_count + low_count
        if total == 0:
            return 0.5
        return high_count / total

    def _assess_agency(self, text: str) -> Agency:
        text_lower = text.lower()
        if any(w in text_lower for w in ["i did", "i made", "i created", "my"]):
            return Agency.SELF
        if any(w in text_lower for w in ["you", "it", "they", "the system"]):
            return Agency.OTHER
        return Agency.CIRCUMSTANCE

    def _determine_tone(self, congruence: float, coping: float) -> EmotionalTone:
        score = (congruence + coping) / 2
        if score >= 0.7:
            return EmotionalTone.POSITIVE
        if score <= 0.3:
            return EmotionalTone.NEGATIVE
        return EmotionalTone.NEUTRAL

    def _determine_goal_status(self, congruence: float, coping: float) -> GoalStatus:
        if congruence >= 0.8 and coping >= 0.7:
            return GoalStatus.ACHIEVED
        if congruence >= 0.5 and coping >= 0.5:
            return GoalStatus.PROGRESSING
        if congruence <= 0.3 and coping <= 0.3:
            return GoalStatus.BLOCKED
        if congruence <= 0.3:
            return GoalStatus.THREATENED
        return GoalStatus.UNKNOWN

    def _assess_engagement(self, text: str) -> float:
        text_lower = text.lower()
        high_engagement = ["let's go", "awesome", "excited", "love", "amazing", "more"]
        low_engagement = ["boring", "tired", "whatever", "don't care", "stop"]
        high_count = sum(1 for w in high_engagement if w in text_lower)
        low_count = sum(1 for w in low_engagement if w in text_lower)
        total = high_count + low_count
        if total == 0:
            return 0.5
        return high_count / total
