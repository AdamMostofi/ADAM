"""Cognitive Appraiser — keyword appraisal along appraisal-theory dimensions.

The dimensions (novelty, goal relevance, goal congruence, coping potential,
agency) come from Cognitive Appraisal Theory (Lazarus & Folkman) and
Scherer's Component Process Model. The mechanism is much simpler than either
theory: each dimension counts words and phrases from a small lexicon,
matched on word boundaries with simple negation (learning/eq/lexicon.py,
Stage 1.7, #37). It reads explicit wording, not meaning: sarcasm, context and
anything outside the lexicon are invisible to it.
"""
from __future__ import annotations

from learning.eq import lexicon
from learning.eq.user_state import UserState, GoalStatus, EmotionalTone, Agency

NOVEL = ["new", "first time", "never", "what is", "how do"]
FAMILIAR = ["again", "still", "another", "more", "continue"]
POSITIVE = ["yes", "correct", "right", "great", "perfect", "thanks", "thank you", "worked", "solved",
            "helpful", "useful", "works", "good", "can't wait",
            # the manual override's emotion words, so a negated one ("not happy") still counts here
            "happy", "love", "awesome", "amazing", "excited"]
NEGATIVE = ["wrong", "error", "errors", "failed", "fail", "fails", "doesn't work", "broken", "broke",
            "issue", "issues", "problem", "problems", "bad", "frustrating", "frustrated", "annoying",
            "angry", "crashed", "confusing",
            "unhappy", "upset", "hate", "stupid", "terrible", "awful"]
# Idioms that would otherwise match a coping phrase: "I can't wait" is eagerness, not inability.
COPING_IDIOMS = ["i can't wait", "can't wait"]
HIGH_COPING = ["i can", "i know", "i understand", "easy", "simple", "clear"]
LOW_COPING = ["i can't", "i don't know", "don't understand", "confusing", "hard", "difficult", "help",
              "frustrating", "frustrated"]
SELF = ["i did", "i made", "i created", "my", "myself"]
OTHER = ["you", "they", "the system"]
HIGH_ENGAGEMENT = ["let's go", "awesome", "excited", "love", "amazing", "more", "can't wait"]
LOW_ENGAGEMENT = ["boring", "tired", "whatever", "don't care", "stop"]


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
        # Novelty isn't polar: "never" is a novelty cue here, so matches are counted, not negated.
        novel = len(lexicon.find(text, NOVEL))
        familiar = len(lexicon.find(text, FAMILIAR))
        return lexicon.ratio(novel, familiar)

    def _assess_relevance(self, text: str) -> float:
        if not self.user_goals:
            return 0.5
        relevant = sum(1 for g in self.user_goals if lexicon.mentions(text, [g.lower()]))
        return min(1.0, relevant / max(len(self.user_goals), 1))

    def _assess_congruence(self, text: str, context: dict | None) -> float:
        pos, neg = lexicon.polarity(text, POSITIVE, NEGATIVE)
        if lexicon.refuses(text):
            neg += 1  # "No, that's wrong"
        return lexicon.ratio(pos, neg)

    def _assess_coping(self, text: str, context: dict | None) -> float:
        return lexicon.ratio(*lexicon.polarity(text, HIGH_COPING, LOW_COPING, ignore=COPING_IDIOMS))

    def _assess_agency(self, text: str) -> Agency:
        if lexicon.mentions(text, SELF):
            return Agency.SELF
        if lexicon.mentions(text, OTHER):
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
        return lexicon.ratio(*lexicon.polarity(text, HIGH_ENGAGEMENT, LOW_ENGAGEMENT))
