"""EQ reduced to one signal: is the user frustrated? (Stage 4.4, #77)

**Why only this.** Stage 4.4 measured what EQ changed after answers came from evidence (Stage 4.3):
- Through the Mouth, nothing visible: 7 and 5 replies shown in 128 samples each, with and without EQ, the
  same generic lines.
- Its only visible output was the CLI's tone label.

The owner chose to keep one signal, read better, and to drop the rest: the appraisal dimensions, the
response parameters, the mood baseline, the manual override and the per-turn save. The measurement is in
docs/design/eq-appraisal.md.

**How a turn is read.** This uses the Stage 1.7 lexicon (`learning.eq.lexicon`: whole words, negation within
three words, "but" contrast, "no" as a refusal), with four rules that are mechanisms, not new words:
- **Questions:** in a yes/no question ("is it wrong?", "was that a bad idea?") the words are asked about, not
  meant, so they count for nothing. Other questions ("why doesn't it work?") are read as usual.
- **Litotes:** a negated negative ("not bad", "I don't hate it", "not unhappy") is weak, so it counts for
  nothing. It isn't flipped into praise, and it isn't a complaint. A negated positive ("not good") is
  negative.
- **Sarcasm cue:** a message that opens with a positive exclamation and then names a failure ("great, it
  broke again") reads as the failure. Other sarcasm is out of reach of word matching.
- **Context:** a terse reply ("fine.", "ok", "whatever") after at least two troubled turns among the last
  three reads as troubled too, so "fine." after repeated failures isn't neutral.

**The signal.** A turn is *troubled* when its negative cues outweigh its positive ones. The user is
*frustrated* when at least two of the last three turns were troubled. It is per session, like attention: it
describes this conversation, so it isn't saved.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass, field

from learning.eq import lexicon
from learning.eq.lexicon import clauses, find

# The Stage 1.7 lexicon, unchanged (it moved here from the retired appraiser).
POSITIVE = ["yes", "correct", "right", "great", "perfect", "thanks", "thank you", "worked", "solved",
            "helpful", "useful", "works", "good", "can't wait",
            "happy", "love", "awesome", "amazing", "excited"]
NEGATIVE = ["wrong", "error", "errors", "failed", "fail", "fails", "doesn't work", "broken", "broke",
            "issue", "issues", "problem", "problems", "bad", "frustrating", "frustrated", "annoying",
            "angry", "crashed", "confusing",
            "unhappy", "upset", "hate", "stupid", "terrible", "awful"]
# The coping lexicon, also unchanged: being able ("i can", "clear") or stuck ("i can't", "don't understand").
HIGH_COPING = ["i can", "i know", "i understand", "easy", "simple", "clear"]
LOW_COPING = ["i can't", "i don't know", "don't understand", "confusing", "hard", "difficult", "help",
              "frustrating", "frustrated"]
POSITIVE = POSITIVE + [p for p in HIGH_COPING if p not in POSITIVE]
NEGATIVE = NEGATIVE + [p for p in LOW_COPING if p not in NEGATIVE]
IDIOMS = ["i can't wait", "can't wait"]
POLAR_QUESTION_START = frozenset({"is", "are", "was", "were", "am", "do", "does", "did", "can", "could", "will",
                                  "would", "should", "has", "have", "had", "isn't", "aren't", "wasn't", "doesn't",
                                  "didn't", "can't", "won't"})
TERSE = frozenset({("fine",), ("ok",), ("okay",), ("whatever",), ("sure",), ("k",), ("right",), ("great",),
                   ("thanks",), ("fine", "whatever"), ("ok", "fine")})
WINDOW = 3


@dataclass
class Reading:
    troubled: bool          # this turn reads as trouble
    frustrated: bool        # at least two of the last three turns did
    level: float            # troubled turns among the last three, 0 to 1
    cues: list[str] = field(default_factory=list)   # what decided it, for the record

    def to_dict(self) -> dict:
        return {"frustrated": self.frustrated, "troubled": self.troubled, "level": round(self.level, 3),
                "cues": list(self.cues)}


def score(text: str) -> tuple[float, list[str]]:
    """Positive minus negative cues for one message, with the four rules; and the cues found."""
    parts = clauses(text)
    if not parts:
        return 0.0, []
    if text.strip().endswith("?") and parts[0] and parts[0][0] in POLAR_QUESTION_START:
        return 0.0, ["yes/no question"]
    cues: list[str] = []
    total = 0.0
    sarcastic = False
    first = parts[0]
    opening_praise = [p for p, negated in find([first], POSITIVE, IDIOMS) if not negated]
    if opening_praise and len(first) <= 2 and len(parts) > 1:
        later = [p for p, negated in find(parts[1:], NEGATIVE) if not negated]
        if later:
            sarcastic = True
            cues.append(f"sarcasm: '{opening_praise[0]}' then '{later[0]}'")
    scope = lexicon.after_contrast(parts)
    for phrase, negated in find(scope, POSITIVE, IDIOMS):
        if sarcastic and phrase in opening_praise:
            continue
        total += -1 if negated else 1
        cues.append(f"not {phrase}" if negated else phrase)
    for phrase, negated in find(scope, NEGATIVE, IDIOMS):
        if negated:
            cues.append(f"litotes: not {phrase}")       # weak: counts for nothing
            continue
        total -= 1
        cues.append(phrase)
    if lexicon.refuses(text):
        total -= 1
        cues.append("refusal")
    return total, cues


class FrustrationReader:
    """Reads each turn of one conversation, in order."""

    def __init__(self, window: int = WINDOW):
        self.recent: collections.deque[bool] = collections.deque(maxlen=window)

    def read(self, text: str) -> Reading:
        value, cues = score(text)
        troubled = value < 0
        tokens = tuple(t for part in clauses(text) for t in part)
        if not troubled and not cues and tokens in TERSE and sum(self.recent) >= 2:
            troubled = True
            cues = [f"terse after {sum(self.recent)} troubled turns"]
        self.recent.append(troubled)
        level = sum(self.recent) / self.recent.maxlen
        return Reading(troubled=troubled, frustrated=sum(self.recent) >= 2, level=level, cues=cues)

    def level(self) -> float:
        """Troubled turns among the last three, 0 to 1."""
        return round(sum(self.recent) / self.recent.maxlen, 3)

    def frustrated(self) -> bool:
        return sum(self.recent) >= 2

    def reset(self) -> None:
        self.recent.clear()
