"""Word and phrase matching for EQ appraisal (Stage 1.7, #37).

Appraisal used to test `phrase in text`, a substring test, so "no" matched
"know", "noon" and "economy", "happy" matched "unhappy", "hate" matched
"whatever", and "i can" matched "i can't". It also ignored negation, so
"this is not great" read as positive.

This module matches whole words instead:

* Text is lowercased, curly apostrophes become straight ones, and it is
  split into clauses at punctuation, then into word tokens ("can't" and
  "let's" are one token each).
* A lexicon entry is one or more words, matched as consecutive tokens.
  Longer entries are matched first and their tokens are used up, so
  "i don't know" is not also "know", and "doesn't work" is not also "work".
* A match is negated when a negator ("not", "never", any "-n't" word, ...)
  appears up to three tokens before it in the same clause. Entries that
  contain a negation themselves ("doesn't work") keep their own meaning.
* A clause that is only "no" (or "nope", "nah") is a negative answer:
  "No, that's wrong". The comma ends the clause, so "wrong" is not negated.
* Contrast: in "X but Y", what follows the last "but" decides the polarity
  ("not perfect but it worked" is positive).
* `ignore` phrases use up their tokens without counting, for idioms that
  would otherwise match: "can't wait" is not "can't".
* Letters repeated three or more times collapse to one ("let's goooo").
"""
from __future__ import annotations

import re

NEGATORS = frozenset({"not", "no", "never", "nothing", "none", "nor", "without", "hardly", "barely"})
NEGATION_WINDOW = 3
REFUSALS = frozenset({("no",), ("nope",), ("nah",), ("no", "way")})
_CLAUSE = re.compile(r"[.,;:!?\n()\"]+")
_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_ELONGATED = re.compile(r"([a-z])\1{2,}")


def clauses(text: str) -> list[list[str]]:
    """Lowercased word tokens, one list per clause."""
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = _ELONGATED.sub(r"\1", text)  # "goooo" -> "go"; doubled letters ("cool") stay
    return [tokens for part in _CLAUSE.split(text) if (tokens := _TOKEN.findall(part))]


def is_negator(token: str) -> bool:
    return token in NEGATORS or token.endswith("n't")


def find(text_or_clauses, phrases, ignore=()) -> list[tuple[str, bool]]:
    """Every lexicon phrase in the text, as (phrase, negated), longest phrases first."""
    parts = clauses(text_or_clauses) if isinstance(text_or_clauses, str) else text_or_clauses
    skip = {tuple(p.split()) for p in ignore}
    entries = sorted({tuple(p.split()) for p in phrases} | skip, key=len, reverse=True)
    hits = []
    for tokens in parts:
        used = [False] * len(tokens)
        for entry in entries:
            n = len(entry)
            for i in range(len(tokens) - n + 1):
                if tuple(tokens[i:i + n]) == entry and not any(used[i:i + n]):
                    for j in range(i, i + n):
                        used[j] = True
                    if entry in skip:
                        continue
                    before = tokens[max(0, i - NEGATION_WINDOW):i]
                    hits.append((" ".join(entry), any(is_negator(t) for t in before)))
    return hits


def after_contrast(parts: list[list[str]]) -> list[list[str]]:
    """The clauses after the last "but", or all of them if there is none."""
    flat = [(c, i, t) for c, tokens in enumerate(parts) for i, t in enumerate(tokens)]
    last = max((k for k, (_, _, t) in enumerate(flat) if t == "but"), default=None)
    if last is None:
        return parts
    c, i, _ = flat[last]
    rest = [parts[c][i + 1:]] + parts[c + 1:]
    return [tokens for tokens in rest if tokens]


def polarity(text: str, positive, negative, ignore=(), contrast: bool = True) -> tuple[int, int]:
    """(positive count, negative count); a negated match counts for the other side."""
    parts = after_contrast(clauses(text)) if contrast else clauses(text)
    pos = neg = 0
    for phrase, negated in find(parts, positive, ignore):
        if negated:
            neg += 1
        else:
            pos += 1
    for phrase, negated in find(parts, negative, ignore):
        if negated:
            pos += 1
        else:
            neg += 1
    return pos, neg


def explicit(text: str, phrases) -> int:
    """How many phrases occur un-negated, anywhere in the text."""
    return sum(1 for _, negated in find(text, phrases) if not negated)


def refuses(text: str) -> bool:
    """A clause that is just "no": a negative answer."""
    return any(tuple(tokens) in REFUSALS for tokens in clauses(text))


def mentions(text: str, phrases) -> bool:
    """Whether any phrase occurs (negated or not)."""
    return bool(find(text, phrases))


def ratio(pos: int, neg: int) -> float:
    total = pos + neg
    return 0.5 if total == 0 else pos / total
