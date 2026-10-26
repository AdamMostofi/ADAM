"""Ear/Mouth integration tests — Needle 2 + TinyChat15M (llama-server HTTP)."""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from interface.ear import Ear, UserIntent
from interface.mouth import Mouth


class FakeMouth:
    def format_response(self, user_message: str, params: dict, context: str = "") -> str:
        return f"[MOCK] {user_message}"


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


def test_mouth_build_prompt():
    mouth = Mouth(auto_start=False)
    prompt = mouth._build_prompt(
        "hello",
        {"warmth": "high", "depth": "summary", "tone": "neutral"},
        context="socrates is man",
    )
    assert "You are ADAM" in prompt
    assert "high warmth" in prompt
    assert "summary depth" in prompt
    assert "socrates is man" in prompt
    assert "hello" in prompt
    assert prompt.startswith("<|im_start|>system")
    assert prompt.endswith("<|im_start|>assistant\n")


def test_mouth_small_talk_bypasses_model():
    mouth = Mouth(auto_start=False)

    def no_model(*args, **kwargs):
        raise AssertionError("small talk must not call the model")

    mouth.speak = no_model
    assert "ADAM" in mouth.format_response("Hello!", {})
    assert mouth.format_response("who are you?", {}) == (
        "I am ADAM, a local machine intelligence with a persistent memory."
    )


def test_mouth_format_response():
    mouth = Mouth(auto_start=False)
    captured = {}

    def fake_speak(prompt, max_tokens=120, stop=None):
        captured["prompt"] = prompt
        return "ok"

    mouth.speak = fake_speak
    result = mouth.format_response("core text", {"warmth": "high", "depth": "summary"})
    assert result == "ok"
    assert "high warmth" in captured["prompt"]
    assert "core text" in captured["prompt"]


def test_mouth_speak_http():
    import json
    from unittest import mock

    mouth = Mouth(auto_start=False)
    fake_response = mock.MagicMock()
    fake_response.read.return_value = json.dumps(
        {"choices": [{"text": " hello there "}]}
    ).encode()
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = False

    with mock.patch("interface.mouth.urllib.request.urlopen", return_value=fake_response):
        result = mouth.speak("hi", max_tokens=10)

    assert result == "hello there"


def test_full_pipeline_with_ear_mouth():
    from interface.core import ADAMCore
    with tempfile.TemporaryDirectory() as tmpdir:
        core = ADAMCore(
            db_path=os.path.join(tmpdir, "test.db"),
            lance_path=os.path.join(tmpdir, "vectors.lance"),
            mouth=FakeMouth(),
        )
        result = core.chat("hello", mode="simple")
        assert "response" in result
        assert "intent" in result
        assert "action" in result["intent"]
        assert "topic" in result["intent"]
