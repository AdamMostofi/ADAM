"""EQ matches words, not substrings (Stage 1.7, #37), and reads one signal: frustration (Stage 4.4, #77).

Updated in Stage 4.4, for a reason: EQ was reduced to a frustration signal (docs/design/eq-appraisal.md), so
the tests of the retired parts (agency, novelty, the manual override, the saved mood baseline) went with them.
The word-matching tests stay, now on what still decides something: whether a turn reads as trouble.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from interface.core import ADAMCore
from learning.eq.frustration import FrustrationReader, score

DATA = Path(__file__).resolve().parents[1] / "data"


def troubled(text: str) -> bool:
    return FrustrationReader().read(text).troubled


# ------------------------------------------------- substring false matches (Stage 1.7)
@pytest.mark.parametrize("text", [
    "I know how this works",          # "know" is not "no"
    "Show me the answer now",         # "now" is not "no"
    "tell me whatever you think",     # "whatever" is not "hate"
    "that was helpful",               # "helpful" is not "help"
    "is seven greater than five",     # "greater" is not "great" (and a question)
    "I can't wait to try it",         # an idiom, not "I can't"
])
def test_a_word_inside_another_word_is_not_a_cue(text):
    assert not troubled(text), score(text)


def test_unhappy_is_not_happy():
    assert troubled("I'm unhappy with this")


def test_i_cant_is_not_i_can():
    assert troubled("I can't do this") and troubled("I can’t do this")   # curly apostrophes too


# ---------------------------------------------------------------- negation
def test_a_negated_positive_is_trouble():
    assert troubled("this is not great") and troubled("not good")


def test_phrases_that_contain_a_negation_keep_their_meaning():
    assert troubled("it doesn't work") and troubled("I don't understand")


def test_real_signals_are_still_found():
    assert troubled("No, that is wrong") and troubled("this is so annoying")
    assert not troubled("Thanks, that worked") and not troubled("let's go!")


# ------------------------------------------------- the four known misses (Stage 1.7), now handled
def test_a_yes_no_question_is_asked_about_not_meant():
    assert not troubled("is it wrong?") and not troubled("was that a bad idea?")
    assert troubled("why does it fail?")                # other questions are read as usual


def test_litotes_is_weak_not_flipped():
    for text in ("I don't hate it", "I'm not unhappy", "not bad"):
        value, cues = score(text)
        assert value == 0 and any(c.startswith("litotes") for c in cues), (text, value, cues)


def test_an_opening_exclamation_then_a_failure_reads_as_the_failure():
    value, cues = score("great, it broke again")
    assert value < 0 and any(c.startswith("sarcasm") for c in cues)
    assert not troubled("great, thanks a lot") and not troubled("I knew you could do it, great")


def test_a_terse_reply_after_repeated_trouble_is_frustration():
    reader = FrustrationReader()
    for text in ("it failed", "still broken", "it broke again"):
        reader.read(text)
    last = reader.read("fine.")
    assert last.troubled and last.frustrated
    calm = FrustrationReader()
    for text in ("it works", "thanks, great"):
        calm.read(text)
    assert not calm.read("fine.").troubled


def test_frustration_needs_two_troubled_turns_of_the_last_three_and_fades():
    reader = FrustrationReader()
    assert not reader.read("it failed").frustrated
    assert reader.read("still broken").frustrated
    assert reader.read("is it a bug?").frustrated            # two of the last three
    assert not reader.read("thanks, that worked").frustrated  # one of the last three


# ------------------------------------------------------- per session, never saved
class QuietMouth:
    def format_response(self, message, params, context=""):
        return "ok"


def test_frustration_is_per_session_and_writes_nothing(tmp_path):
    core = ADAMCore(db_path=str(tmp_path / "m.db"), lance_path=str(tmp_path / "v.db"), mouth=QuietMouth())
    for text in ("it failed", "still broken"):
        result = core.chat(text)
    assert result["frustration"]["frustrated"]
    assert not (tmp_path / "m.db").exists()          # the original store's file is no longer written by EQ
    again = ADAMCore(db_path=str(tmp_path / "m.db"), lance_path=str(tmp_path / "v.db"), mouth=QuietMouth())
    assert not again.chat("hello")["frustration"]["frustrated"]


# ------------------------------------------------- set accuracy, on what the signal decides
def accuracy(name: str) -> tuple[int, int, list[str]]:
    items = json.loads((DATA / name).read_text())["items"]
    misses = [i["text"] for i in items if troubled(i["text"]) != (i["tone"] == "negative")]
    return len(items) - len(misses), len(items), misses


def test_labelled_set_accuracy_does_not_regress():
    correct, total, misses = accuracy("eq_labelled.json")
    assert correct == total, misses


def test_old_held_out_probes():
    correct, total, misses = accuracy("eq_probe.json")
    assert correct == total, misses   # the four known misses are among them


def test_new_held_out_probes_as_measured():
    """Written before this stage's change; scored as is (docs/design/eq-appraisal.md). The misses are words
    the Stage 1.7 lexicon doesn't have; they are recorded, not added, so the set stays held out."""
    correct, total, misses = accuracy("eq_probe_4_4.json")
    assert correct >= 19, misses
    assert set(misses) <= {"wonderful, another crash", "perfect, now nothing loads", "love how it keeps breaking",
                           "this is a disaster", "can't stand it"}
