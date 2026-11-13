"""Appraisal matches words, not substrings, and each turn is recorded once (Stage 1.7, #37)."""
from __future__ import annotations

import sqlite3

import pytest

from interface.core import ADAMCore
from learning.eq.appraiser import CognitiveAppraiser
from learning.eq.engine import EQEngine
from learning.eq.manual_override import ManualOverride
from learning.eq.user_state import Agency, EmotionalTone


@pytest.fixture
def appraiser():
    return CognitiveAppraiser()


# ------------------------------------------------- substring false matches


def test_know_is_not_no(appraiser):
    state = appraiser.appraise("I know how this works")
    assert state.goal_congruence >= 0.5
    assert state.emotional_tone != EmotionalTone.NEGATIVE


def test_now_is_not_no(appraiser):
    assert appraiser.appraise("Show me the answer now").goal_congruence == 0.5


def test_unhappy_is_not_happy():
    state = ManualOverride().detect_override("I'm unhappy with this")
    assert state is None or state.emotional_tone != EmotionalTone.POSITIVE


def test_whatever_is_not_hate():
    assert ManualOverride().detect_override("tell me whatever you think") is None


def test_i_cant_is_not_i_can(appraiser):
    assert appraiser.appraise("I can't do this").coping == 0.0


def test_economy_is_not_my(appraiser):
    assert appraiser.appraise("the economy is growing").agency != Agency.SELF


def test_with_is_not_it(appraiser):
    assert appraiser.appraise("rain falls with wind").agency == Agency.CIRCUMSTANCE


def test_knew_is_not_new(appraiser):
    assert appraiser.appraise("I knew that already").novelty == 0.5


def test_helpful_is_not_help(appraiser):
    assert appraiser.appraise("that was helpful").coping >= 0.5


def test_greater_is_not_great():
    assert ManualOverride().detect_override("is seven greater than five") is None


# ---------------------------------------------------------------- negation


def test_not_great_is_not_positive():
    state = EQEngine(":memory:").process_input("this is not great")[0]
    assert state.emotional_tone != EmotionalTone.POSITIVE


def test_not_broken_is_not_negative(appraiser):
    assert appraiser.appraise("it is not broken anymore").goal_congruence >= 0.5


def test_phrases_that_contain_a_negation_keep_their_meaning(appraiser):
    assert appraiser.appraise("it doesn't work").goal_congruence == 0.0
    assert appraiser.appraise("I don't understand").coping == 0.0


def test_curly_apostrophes_are_read_like_straight_ones(appraiser):
    assert appraiser.appraise("I can’t do this").coping == 0.0


# --------------------------------------------------------- still matches


def test_real_signals_are_still_found(appraiser):
    assert appraiser.appraise("No, that is wrong").goal_congruence == 0.0
    assert appraiser.appraise("Thanks, that worked").goal_congruence == 1.0
    assert appraiser.appraise("I did it myself, my code").agency == Agency.SELF
    assert ManualOverride().detect_override("this is so annoying").emotional_tone == EmotionalTone.NEGATIVE
    assert ManualOverride().detect_override("let's go!").emotional_tone == EmotionalTone.POSITIVE


# ------------------------------------------------------- one record per turn


class QuietMouth:
    def format_response(self, message, params, context=""):
        return "ok"


def test_one_turn_adds_one_record(tmp_path):
    core = ADAMCore(db_path=str(tmp_path / "m.db"), lance_path=str(tmp_path / "v.db"), mouth=QuietMouth())
    history, states = core.eq.baseline.get_history_size(), len(core.eq.tracker.get_history())
    core.chat("hello there")
    assert core.eq.baseline.get_history_size() == history + 1
    assert len(core.eq.tracker.get_history()) == states + 1


def test_saving_keeps_one_row_and_the_history(tmp_path):
    db = str(tmp_path / "m.db")
    eq = EQEngine(db)
    for text in ("thanks, that worked", "great, solved", "perfect"):
        eq.process_input(text)
        eq.save()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM eq_state").fetchone()[0] == 1
    restored = EQEngine(db)
    assert restored.baseline.get_history_size() == 3
    baseline = restored.get_baseline()
    restored.process_input("hello")  # one neutral turn must not reset the learned baseline
    assert restored.get_baseline() == pytest.approx(baseline * 3 / 4)


# ------------------------------------------------- labelled-set accuracy

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def accuracy(name: str) -> tuple[int, int, list[str]]:
    items = json.loads((DATA / name).read_text())["items"]
    misses = [i["text"] for i in items
              if EQEngine(":memory:").process_input(i["text"])[0].emotional_tone.value != i["tone"]]
    return len(items) - len(misses), len(items), misses


def test_labelled_set_accuracy_does_not_regress():
    correct, total, misses = accuracy("eq_labelled.json")
    assert correct == total, misses  # 25/38 before Stage 1.7


def test_held_out_probe_accuracy_does_not_regress():
    correct, total, misses = accuracy("eq_probe.json")
    assert correct >= 20, misses
    # Known limits of keyword appraisal, recorded rather than tuned away (docs/design/eq-appraisal.md).
    assert set(misses) <= {"is it wrong?", "great, it broke again", "I don't hate it", "I'm not unhappy"}
