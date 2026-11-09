"""Ear — Needle wrapper for structured intent extraction.

If Needle cannot be loaded (for example its native library can't be
downloaded on a fresh machine), the Ear falls back to its keyword method
and records why in `unavailable_reason`, so ADAM still starts.
"""
from __future__ import annotations

import logging
from typing import cast

from pydantic import BaseModel

log = logging.getLogger(__name__)

_POSITIVE = ("great", "good", "awesome", "amazing", "love", "fantastic")
_NEGATIVE = ("terrible", "awful", "bad", "hate", "horrible", "frustrating")


class UserIntent(BaseModel):
    action: str = "unknown"
    topic: str = "general"
    sentiment: str = "neutral"
    urgency: str = "normal"


def keyword_intent(text: str) -> UserIntent:
    lowered = text.lower()
    if any(w in lowered for w in _POSITIVE):
        sentiment = "positive"
    elif any(w in lowered for w in _NEGATIVE):
        sentiment = "negative"
    else:
        sentiment = "neutral"
    return UserIntent(action="unknown", topic=text[:50], sentiment=sentiment)


class Ear:
    def __init__(self):
        self._schema = UserIntent.model_json_schema()
        self.unavailable_reason: str | None = None
        try:
            from needle import Needle
            self._needle = Needle()
        except Exception as exc:  # noqa: BLE001 - any load failure means "use the fallback"
            self._needle = None
            self.unavailable_reason = f"{type(exc).__name__}: {exc}"[:300]
            log.warning("Needle unavailable; the Ear is using keyword fallback (%s)", self.unavailable_reason)

    @property
    def available(self) -> bool:
        return self._needle is not None

    def listen(self, text: str) -> UserIntent:
        if self._needle is None:
            return keyword_intent(text)
        result = self._needle.extract(text, self._schema)
        if result is None:
            return keyword_intent(text)
        if isinstance(result, dict):
            return UserIntent(**{k: v for k, v in result.items() if k in UserIntent.model_fields})
        return cast(UserIntent, result)

    def close(self):
        if self._needle is not None:
            self._needle.close()
