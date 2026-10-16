"""Ear — Needle 2 wrapper for structured intent extraction."""
from __future__ import annotations

from typing import cast
from pydantic import BaseModel


class UserIntent(BaseModel):
    action: str = "unknown"
    topic: str = "general"
    sentiment: str = "neutral"
    urgency: str = "normal"


class Ear:
    def __init__(self):
        from needle import Needle
        self._needle = Needle()
        self._schema = UserIntent.model_json_schema()

    def listen(self, text: str) -> UserIntent:
        result = self._needle.extract(text, self._schema)
        if result is None:
            sentiment = "positive" if any(w in text.lower() for w in ["great", "good", "awesome", "amazing", "love", "fantastic"]) else \
                        "negative" if any(w in text.lower() for w in ["terrible", "awful", "bad", "hate", "horrible", "frustrating"]) else "neutral"
            return UserIntent(action="unknown", topic=text[:50], sentiment=sentiment)
        if isinstance(result, dict):
            return UserIntent(**{k: v for k, v in result.items() if k in UserIntent.model_fields})
        return cast(UserIntent, result)

    def close(self):
        self._needle.close()
