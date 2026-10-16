"""Ear/Mouth integration tests — Needle 2 + TinyChat pipeline."""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from interface.ear import Ear, UserIntent
from interface.mouth import Mouth


def test_ear_listen():
    ear = Ear()
    intent = ear.listen("hello, how are you?")
    assert isinstance(intent, UserIntent)
    assert intent.action != ""
    assert intent.topic != ""
    ear.close()


def test_ear_sentiment_positive():
    ear = Ear()
    intent = ear.listen("this is great and amazing")
    assert intent.sentiment == "positive"
    ear.close()


def test_ear_sentiment_negative():
    ear = Ear()
    intent = ear.listen("this is terrible and awful")
    assert intent.sentiment == "negative"
    ear.close()


def test_mouth_speak():
    mouth = Mouth()
    response = mouth.speak("Hello", max_tokens=20)
    assert isinstance(response, str)
    assert len(response) > 0


def test_mouth_format_response():
    mouth = Mouth()
    response = mouth.format_response("Based on what I know: hello", {"warmth": "high", "depth": "summary"})
    assert isinstance(response, str)
    assert len(response) > 0


def test_full_pipeline_with_ear_mouth():
    from interface.core import ADAMCore
    with tempfile.TemporaryDirectory() as tmpdir:
        core = ADAMCore(
            db_path=os.path.join(tmpdir, "test.db"),
            lance_path=os.path.join(tmpdir, "vectors.lance"),
        )
        result = core.chat("hello", mode="simple")
        assert "response" in result
        assert "intent" in result
        assert "action" in result["intent"]
        assert "topic" in result["intent"]
