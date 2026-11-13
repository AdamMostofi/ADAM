# EQ appraisal: what it actually does

Stage 1.7 (#37). DE.1: fix first, then question the value later. EQ currently
only shapes the tone sent to the Mouth, and #34 narrows that further. Whether
it earns its place gets reviewed once #34 lands.

## Mechanism

The dimensions come from appraisal theory: novelty, goal relevance, goal
congruence, coping potential and agency (Lazarus and Folkman; Scherer's
Component Process Model). The mechanism is **keyword counting**, not a model
of appraisal:

- **One lexicon per dimension.** Each dimension has a small word-and-phrase
  lexicon (`learning/eq/appraiser.py`), and its score is the share of
  positive matches.
- **Tone** comes from congruence and coping.
- **Manual override.** Explicit emotion words, un-negated, such as "annoying"
  or "let's go", replace the appraisal for that turn
  (`learning/eq/manual_override.py`).

It reads explicit wording. Sarcasm, context, and anything outside the
lexicons are invisible to it.

## Matching (`learning/eq/lexicon.py`)

**Before:** every lexicon entry was matched with `entry in text`, a
substring test:

| Text | Read as | Because |
|---|---|---|
| "I know how this works" | negative | "no" is inside "know" |
| "My train leaves at noon" | negative | "no" is inside "noon" |
| "Tell me about the economy of Spain" | negative | "no" is inside "economy" |
| "I'm unhappy with this answer" | positive (override) | "happy" is inside "unhappy" |
| "tell me whatever you think" | negative (override) | "hate" is inside "whatever" |
| "I can't do this" | able and unable | "i can" is inside "i can't" |
| "rain falls with wind" | another person's doing | "it" is inside "with" |
| "This is not great" | positive | no negation |

**Now:**
- **Whole words.** Text is lowercased, curly apostrophes are straightened,
  and the text is split into clauses at punctuation and then into word
  tokens.
- **Longest first.** Entries match as consecutive tokens, longest first, and
  a match uses up its tokens. So "i don't know" is not also "know".
- **Negation.** A negator ("not", "never", any "-n't" word) up to three
  tokens before a match, in the same clause, flips it, unless the entry is
  itself negative ("doesn't work").
- **Refusals.** A clause that is only "no" is a refusal, so "No, that's
  wrong" stays negative.
- **Contrast.** In "X but Y", Y decides the appraisal. The manual override
  ignores contrast: an explicit emotion word counts anywhere.
- **Idioms.** These use up their tokens: "can't wait" is not "can't".
- **Elongated words collapse:** "let's goooo" becomes "let's go".
- **Bigger lexicons.** They gained common words that were missing: "bad",
  "fail", "fails", "broke", the plurals "errors" and "problems", "helpful",
  "useful", and the override's emotion words. A negated emotion word ("not
  happy") goes to the appraisal instead of forcing an override.

## One record per turn

`EQEngine.process_input` records the turn in the tracker and the baseline,
and `ADAMCore.chat` recorded it again, so every turn counted twice and the
baseline was skewed. `chat` now leaves the recording to `process_input`.

The saved state had two problems as well:
- **It grew forever.** `eq_state` gained a row on every chat turn, though only
  the newest was ever read. There is now one row, replaced on each save.
- **The history was lost.** It didn't include the interaction history, so
  the first turn after a restart recomputed the baseline from that turn
  alone (0 or 1). The history (at most 10 turns) is now saved too.

## Accuracy

`scripts/measure_eq.py` scores tone end to end (override, then appraisal).
The results are in `docs/measurements/2026-11-13-eq-before.json` and
`-after.json`.

| Set | Before | After |
|---|---|---|
| Labelled set (`tests/data/eq_labelled.json`, 38 sentences) | 25/38 (65.8%) | 38/38 (100%) |
| Held-out probes (`tests/data/eq_probe.json`, 24 sentences) | 10/24 (41.7%) | 20/24 (83.3%) |

**Read the 100% with care.** The labelled set was written alongside the fix,
so it shows the targeted defects are gone, not that EQ reads people
correctly. The probe set was written afterwards to break it, and its score
is recorded as is. Its remaining misses are the limits of keyword appraisal:

- **Sarcasm:** "great, it broke again" reads as positive.
- **Questions:** "is it wrong?" reads as negative.
- **Litotes:** "I don't hate it" and "I'm not unhappy" read as positive (the
  labels say neutral; this is debatable).

Tests keep both scores from regressing (`tests/unit/test_eq_appraisal_matching.py`).
