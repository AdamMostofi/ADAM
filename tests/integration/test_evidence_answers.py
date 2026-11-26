"""Stage 4.3 (#34): ADAM answers only from evidence, and never states a fact it can't back."""
from __future__ import annotations

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from interface import evidence
from interface.evidence import (ACKNOWLEDGEMENT, MODEL, NO_EVIDENCE, PASSAGE, PROOF, SMALL_TALK, Answerer, Terms,
                                Wording, model_text_is_grounded, words)
from interface.mouth import small_talk
from kernel.engine import InferenceEngine
from kernel.facts import Fact

LIE = "Socrates is a fish who lives on the moon."

SOCRATES = [("socrates", "instance_of", "man"), ("man", "subclass_of", "mortal"),
            ("mortal", "subclass_of", "animal"), ("plato", "instance_of", "man"),
            ("rock", "not_instance_of", "animal"), ("tweety", "instance_of", "bird"),
            ("bird", "typically", "flier")]


class LyingMouth:
    """Says something false every time: none of it may ever reach a reply."""

    def __init__(self, text=LIE):
        self.text, self.calls = text, 0

    def format_response(self, message, params, context=""):
        self.calls += 1
        return self.text


def engine_with(facts, origin=""):
    engine = InferenceEngine()
    for s, p, o in facts:
        engine.add_fact(Fact(s, p, o, origin=origin))
    engine.infer()
    return engine


@pytest.fixture
def answerer():
    return Answerer(engine_with(SOCRATES), mouth=LyingMouth(), small_talk=small_talk)


def facts_in(answer) -> set[tuple[str, ...]]:
    return {tuple(step["fact"].split(" ")) for e in answer.evidence if e["type"] == "proof" for step in e["steps"]}


# ------------------------------------------------------------ acceptance
def test_every_factual_sentence_comes_from_a_proof(answerer):
    a = answerer.answer("Is Socrates mortal?")
    assert a.answer_source == PROOF
    assert a.text.endswith("Socrates is a man and every man is a mortal, so Socrates is a mortal.")
    (proof,) = a.evidence
    assert proof["claim"] == "socrates instance_of mortal"
    assert [s["fact"] for s in proof["steps"]] == ["man subclass_of mortal", "socrates instance_of man",
                                                   "socrates instance_of mortal"]
    assert [s["rule"] for s in proof["steps"]][:2] == ["given", "given"]


def test_a_question_whose_words_match_no_fact_verbatim(answerer):
    """No stored fact says "men" or "animals": the plurals resolve to terms, and the answer is proved."""
    a = answerer.answer("Are men animals?")
    assert a.answer_source == PROOF and a.text.startswith(("Yes", "That's right"))
    assert ("man", "subclass_of", "animal") in facts_in(a)
    assert not any(w in a.text.lower() for w in ("men ", "animals"))


def test_without_evidence_nothing_is_asserted(answerer):
    for q in ("Is Socrates a bird?", "Who won the 1998 World Cup?", "What is a fact?", "Is plato wise?"):
        a = answerer.answer(q)
        assert a.answer_source == NO_EVIDENCE and a.evidence == [], q
        assert re.search(r"\b(don't know|can't confirm|won't guess|nothing I can back up|won't say)\b", a.text), a.text
        assert not a.text.startswith(("Yes", "No.", "That's right"))
    assert answerer.mouth.calls == 0          # the Mouth isn't asked to answer a question


def test_a_negation_is_answered_no_with_its_proof(answerer):
    a = answerer.answer("Is a rock an animal?")
    assert a.answer_source == PROOF and a.text.startswith(("No", "Actually, no")) and "isn't an animal" in a.text


def test_a_default_is_said_as_probable(answerer):
    a = answerer.answer("Is Tweety a flier?")
    assert a.answer_source == PROOF and "so probably Tweety is a flier" in a.text


def test_small_talk_still_works(answerer):
    for message in ("hello", "Hi!", "how are you?", "thanks", "who are you?", "what can you do?"):
        a = answerer.answer(message)
        assert a.answer_source == SMALL_TALK and a.text and LIE not in a.text, message


def test_what_and_who_questions_list_proven_beliefs_only(answerer):
    a = answerer.answer("What is Socrates?")
    assert a.answer_source == PROOF and a.text.startswith("Socrates is a man, a mortal, and an animal")
    claims = {e["claim"] for e in a.evidence}
    assert claims == {"socrates instance_of man", "socrates instance_of mortal", "socrates instance_of animal"}
    who = answerer.answer("Who is mortal?")
    assert who.text.startswith("Plato is a mortal, and so is Socrates.") and "Exists" not in who.text
    assert answerer.answer("tell me about men").text.startswith("Every man is a mortal and an animal.")


# ------------------------------------------------------------ statements and chatter
def test_a_statement_is_checked_never_just_agreed_with(answerer):
    assert answerer.answer("Socrates is a man.").answer_source == PROOF
    wrong = answerer.answer("Rock is an animal")
    assert wrong.answer_source == PROOF and wrong.text.startswith(("That doesn't match", "Actually, no", "I have it"))
    unknown = answerer.answer("Socrates was wise")
    assert unknown.answer_source == NO_EVIDENCE and unknown.text.startswith("I can't confirm that")


def test_the_mouths_words_never_reach_a_reply_unless_they_assert_nothing():
    lying = Answerer(engine_with(SOCRATES), mouth=LyingMouth(), small_talk=small_talk)
    a = lying.answer("I like pizza")
    assert a.answer_source == ACKNOWLEDGEMENT and LIE not in a.text and lying.mouth.calls == 1
    polite = Answerer(engine_with(SOCRATES), mouth=LyingMouth("What do you think about that?"), small_talk=small_talk)
    assert polite.answer("I like pizza").answer_source == MODEL


class BrokenMouth:
    def format_response(self, message, params, context=""):
        raise ConnectionError("no llama-server")


def test_no_mouth_still_gives_a_plain_reply():
    a = Answerer(engine_with(SOCRATES), mouth=BrokenMouth(), small_talk=small_talk).answer("I like pizza")
    assert a.answer_source == ACKNOWLEDGEMENT


@pytest.mark.parametrize("text, ok", [
    # what TinyChat15M actually said when asked to phrase facts or chat (2026-11-25): all refused but one
    ("it sounds like a great adventure for you and you to plan for.", False),
    ("do you think it will be a popular choice for everyone?", False),
    ("can help us understand why people would choose to join such a record for phones?", False),
    ("it seems like a lot of excuses for the same prose and jokes", False),
    ("what do you think about that?", True),
    ("Socrates is a fish.", False),
    ("I have 3 cats.", False),
    ("do you really like pizza?", True),        # a question back, in the user's own words
    ("pizza is healthy.", False),               # the user's word, but asserted: refused
    ("", False),
])
def test_the_model_gate(text, ok):
    assert model_text_is_grounded(text, "I like pizza") is ok


# ------------------------------------------------------------ conflicts
def test_contested_evidence_is_not_answered_either_way():
    engine = InferenceEngine()
    engine.add_fact(Fact("road", "is", "wet", origin="alice"))
    engine.add_fact(Fact("road", "not_is", "wet", origin="bob"))
    engine.infer()
    a = Answerer(engine, small_talk=small_talk).answer("Is the road wet?")
    assert a.answer_source == NO_EVIDENCE and "won't say" in a.text and a.evidence == []


# ------------------------------------------------------------ passages
class OnePassage:
    """A stand-in for the source library with one passage."""

    def __init__(self, text):
        from memory.source_library import Passage, passage_key, sha256
        self.p = Passage(passage_key("abc", 3), "abc", "apology.md", 3, 10, 10 + len(text), sha256(text), text, 1.0)

    def search_passages(self, query, limit=5):
        return [self.p]


def test_a_passage_answer_quotes_it_exactly_with_its_citation():
    text = "The unexamined life is not worth living, said Socrates at his trial."
    a = Answerer(engine_with(SOCRATES), library=OnePassage(text), small_talk=small_talk).answer(
        "What did Socrates say about the unexamined life?")
    assert a.answer_source == PASSAGE and f"“{text}”" in a.text and "paragraph 4" in a.text
    (cite,) = a.evidence
    assert cite["name"] == "apology.md" and cite["text"] == text and (cite["start"], cite["end"]) == (10, 10 + len(text))


def test_a_passage_that_doesnt_cover_the_question_isnt_cited():
    a = Answerer(engine_with(SOCRATES), library=OnePassage("Life in Athens was busy."),
                 small_talk=small_talk).answer("What did Socrates say about the unexamined life?")
    assert a.answer_source == NO_EVIDENCE


def test_a_proof_comes_before_a_passage():
    a = Answerer(engine_with(SOCRATES), library=OnePassage("Socrates was mortal, as every man is."),
                 small_talk=small_talk).answer("Is Socrates mortal?")
    assert a.answer_source == PROOF


# ------------------------------------------------------------ the property: no reply ever goes beyond its evidence
NAMES = ["ann", "bob", "cid", "dee"]
CLASSES = ["cat", "dog", "pet", "animal", "thing"]


@settings(max_examples=150, deadline=None)
@given(
    members=st.lists(st.tuples(st.sampled_from(NAMES), st.sampled_from(CLASSES)), max_size=5),
    subs=st.lists(st.tuples(st.sampled_from(CLASSES), st.sampled_from(CLASSES)).filter(lambda t: t[0] != t[1]),
                  max_size=4),
    negs=st.lists(st.tuples(st.sampled_from(NAMES), st.sampled_from(CLASSES)), max_size=2),
    question=st.tuples(st.sampled_from(NAMES + CLASSES), st.sampled_from(CLASSES)),
)
def test_no_reply_goes_beyond_its_evidence(members, subs, negs, question):
    facts = ([(n, "instance_of", c) for n, c in members] + [(a, "subclass_of", b) for a, b in subs]
             + [(n, "not_instance_of", c) for n, c in negs])
    engine = engine_with(facts)
    answerer = Answerer(engine, mouth=LyingMouth(), small_talk=small_talk)
    s, o = question
    for message in (f"Is {s} {'an' if o[0] in 'aeiou' else 'a'} {o}?", f"What is {s}?", f"Who is {o}?",
                    f"{s} is {'an' if o[0] in 'aeiou' else 'a'} {o}"):
        a = answerer.answer(message)
        assert LIE not in a.text
        if a.answer_source != PROOF:
            assert a.evidence == [] and not a.text.startswith(("Yes", "That's right", "No.")), (message, a.text)
            continue
        # Every proof is real: each step's fact is held by the engine, and is active.
        for e in a.evidence:
            for step in e["steps"]:
                assert engine.query(*step["fact"].split(" ")), (message, step)
        # Every word of the reply is a word of its evidence or of the fixed wording.
        allowed = {w for e in a.evidence for step in e["steps"] for t in step["fact"].split(" ")[::2] for w in words(t)}
        allowed |= {w for phrase in (*evidence._YES, *evidence._NO, *evidence._CONFIRM, *evidence._CONTRADICT)
                    for w in words(phrase)}
        allowed |= set(words("and since so probably every is a an isn't are each"))
        stray = [w for w in words(a.text) if w not in allowed]
        assert not stray, (message, a.text, stray)


# ------------------------------------------------------------ through the core and /api/chat
@pytest.fixture
def core(tmp_path):
    from interface.core import ADAMCore
    core = ADAMCore(db_path=str(tmp_path / "adam_memory.db"), lance_path=str(tmp_path / "adam_vectors.db"),
                    mouth=LyingMouth())
    for f in SOCRATES:
        core.add_fact(*f)
    return core


def test_chat_keeps_its_keys_and_adds_the_answer_source(core):
    from interface.web.app import create_app
    client = create_app(core).test_client()
    body = client.post("/api/chat", json={"message": "Is Socrates mortal?"}).get_json()
    assert {"response", "intent", "state", "params", "memories_used"} <= set(body)   # unchanged keys
    assert body["answer_source"] == PROOF and body["evidence"][0]["claim"] == "socrates instance_of mortal"
    assert client.post("/api/chat", json={"message": "hello"}).get_json()["answer_source"] == SMALL_TALK


def test_chat_quotes_a_passage_from_the_library(core, tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "apology.md").write_text("# Apology\n\nThe unexamined life is not worth living.\n")
    library = core.memory.source_library()
    library.workspace = workspace.resolve()
    key = library.ingest("apology.md")["source"]
    result = core.chat("Is the unexamined life worth living?")
    assert result["answer_source"] == PASSAGE
    (cite,) = result["evidence"]
    assert library.source_text(key)[cite["start"]:cite["end"]] == cite["text"] in result["response"]


def test_the_wording_says_exactly_what_each_fact_says():
    engine = engine_with(SOCRATES)
    w = Wording(Terms(engine))
    assert w.clause(("socrates", "instance_of", "man")) == "Socrates is a man"
    assert w.clause(("man", "subclass_of", "animal")) == "every man is an animal"
    assert w.clause(("rock", "not_instance_of", "animal")) == "Rock isn't an animal"
    assert w.clause(("bird", "typically", "flier")) == "a bird is typically a flier"
    assert w.clause(("ice_cream", "melts_in", "sun")) == "ice cream melts in sun"
