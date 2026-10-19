"""Ear/Mouth integration tests — Needle 2 + TinyChat15M (llama-server HTTP)."""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from interface.ear import Ear, UserIntent
from interface.mouth import Mouth


class FakeMouth:
    def format_response(self, core_response: str, params: dict) -> str:
        return f"[MOCK] {core_response}"


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
    prompt = mouth._build_prompt("Based on what I know: hello", {"warmth": "high", "depth": "summary"})
    assert "warmth=high" in prompt
    assert "depth=summary" in prompt
    assert "Based on what I know: hello" in prompt
    assert prompt.endswith("[OUTPUT]")


def test_mouth_format_response():
    mouth = Mouth(auto_start=False)
    captured = {}

    def fake_speak(prompt, max_tokens=100):
        captured["prompt"] = prompt
        return "ok"

    mouth.speak = fake_speak
    result = mouth.format_response("core text", {"warmth": "high", "depth": "summary"})
    assert result == "ok"
    assert "warmth=high" in captured["prompt"]
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
