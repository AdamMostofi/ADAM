# EQ: what it does

**Status:** Current. Stage 4.4, Revisit the Appraisal ([#77](https://github.com/AdamMostofi/ADAM/issues/77)),
reduced EQ to one signal: **is the user frustrated?** Stage 1.7 ([#37](https://github.com/AdamMostofi/ADAM/issues/37))
is kept below as history.

## Stage 4.4: measure first, then decide (DE.2)

**What EQ changed once answers came from evidence.** Stage 4.3 made factual replies come only from proofs and
quoted passages, so EQ's parameters (warmth, depth, tone) could reach a user only through the Mouth, for
chatter. `scripts/measure_eq.py`, at commit ec2d2d3, measured this on a chat session written for the purpose
(`tests/data/eq_session.json`, 36 turns, written before the measurement). Its report is
[2026-11-26-eq-value.json](../measurements/2026-11-26-eq-value.json):

| | |
|---|---|
| Turns whose reply could come from the Mouth (chatter) | 16 of 36 |
| Turns where EQ's parameters differed from neutral | 8 of 36; 6 of the 16 Mouth turns |
| Real TinyChat15M replies shown, 8 samples per Mouth turn, with EQ's parameters | 7 of 128 |
| The same, with neutral parameters | 5 of 128 |
| What those replies were | the same generic lines either way ("what do you think?") |
| The CLI's tone label (`ADAM [negative]`), the only other thing a user saw | right on 27 of 36 turns |
| New held-out probes, as is (three tones) | 11 of 24 |

**No recorded real chat turns existed.**
- The production store was reset on 2026-11-11.
- EQ saved tone states, but not the text behind them.
- The web UI keeps its transcript in the browser.

So the session was written for the purpose, before anything was measured.

**The decision (DE.2, the owner's call, 2026-11-26): reduce.**
- **Kept:** one signal, frustration, read better.
- **Removed:** the appraisal dimensions (novelty, relevance, congruence, coping, agency), the response
  parameters, the mood baseline, the manual override and the saved state. About 520 lines went, with the 42
  tests that covered them.

## The frustration signal (`learning/eq/frustration.py`)

**A turn reads as troubled** when its negative cues outweigh its positive ones. The lexicon is the Stage 1.7
one, unchanged: whole words, negation within three words, "but" contrast, "no" as a refusal. It includes the
coping words ("I can't", "don't understand", "help"). Four rules, written as mechanisms rather than new words:

| Rule | Example | Read as |
|---|---|---|
| A yes/no question is asked about, not meant | "is it wrong?", "was that a bad idea?" | nothing |
| Litotes is weak, not flipped | "not bad", "I don't hate it", "I'm not unhappy" | nothing (a negated positive, "not good", is still trouble) |
| An opening exclamation, then a failure | "great, it broke again" | the failure |
| A terse reply after repeated trouble | "fine." after two troubled turns of the last three | trouble |

**The user is frustrated** when two of the last three turns were troubled. It is per session, like
attention: it describes this conversation, so it is never saved. EQ no longer writes `eq_state` to
`adam_memory.db` on every turn; with the engine store, that file is no longer created at all.

**What it changes:**
- **ADAM's own wording.** Its fixed wording for what it can't do ("I won't guess", an acknowledgement) starts
  with an apology: "Sorry about that. …"
- **The Mouth.** It isn't used for chatter while the user is frustrated.
- **The CLI.** It shows `ADAM [frustrated]` with a red border.
- **The stats panel.** It shows the frustration level.
- **Facts and passages never change.**

`/api/chat` keeps its `state` and `params` keys for clients. `state.emotional_tone` is now "negative" for a
troubled turn and "neutral" otherwise, and `params` is fixed. A new `frustration` key carries the signal and
the cues that decided it.

## Accuracy, on what the signal decides

A turn is right when it reads as troubled exactly when its label is negative. Both readers are scored the same
way, from `scripts/measure_eq.py` ([2026-11-27-eq-frustration.json](../measurements/2026-11-27-eq-frustration.json)):

| Set | Old EQ (as negative) | Frustration reader |
|---|---|---|
| Labelled set (`eq_labelled.json`, 38) | 38/38 | 38/38 |
| Stage 1.7 held-out probes (`eq_probe.json`, 24) | 22/24 | 24/24 |
| Stage 4.4 held-out probes (`eq_probe_4_4.json`, 24, written before the change) | 16/24 | 19/24 |
| "fine." after repeated failures (`eq_probe_4_4.json` sequences) | wrong | right |
| The chat session (`eq_session.json`, 36) | 30/36 | 31/36 |

**The four known misses from Stage 1.7 are fixed:** "is it wrong?", "great, it broke again", "I don't hate
it" and "I'm not unhappy".

**What it still misses.** Each of these is a word or form the Stage 1.7 lexicon doesn't have. They are recorded
here, not added, so the held-out sets stay held out:
- "wonderful, another crash" and "perfect, now nothing loads": neither "crash" nor "nothing loads" is a
  failure word.
- "love how it keeps breaking": "breaking" isn't in the lexicon ("broke" and "broken" are), and the sarcasm
  isn't at the start.
- "this is a disaster", "can't stand it", "that's useless", "I'm tired today", "that's not what I asked".
- **Sarcasm beyond an opening exclamation is out of reach of word matching.**

Because of these gaps, frustration never triggered in the 36-turn session.

## Stage 1.7: matching words, not substrings (history)

Stage 1.7 (#37, DE.1: fix first, question the value later) made the matching sound. It is the base the
frustration reader uses (`learning/eq/lexicon.py`). **Before**, every entry was matched as a substring:

| Text | Read as | Because |
|---|---|---|
| "I know how this works" | negative | "no" is inside "know" |
| "Tell me about the economy of Spain" | negative | "no" is inside "economy" |
| "I'm unhappy with this answer" | positive | "happy" is inside "unhappy" |
| "tell me whatever you think" | negative | "hate" is inside "whatever" |
| "I can't do this" | able and unable | "i can" is inside "i can't" |
| "This is not great" | positive | no negation |

**After:**
- **Whole words.** Matching is on word tokens, per clause, longest entry first, and a match uses up its
  tokens.
- **Negation.** A negator within three tokens negates a match.
- **Refusals.** "no" on its own is a refusal.
- **Contrast.** In "X but Y", Y decides.
- **Idioms.** "can't wait" is not "can't".
- **Elongation.** Elongated words collapse ("goooo" becomes "go").

It also fixed double-recorded turns and an `eq_state` table that grew on every turn; both went with the
saved state in Stage 4.4.

Its scores (three tones, `docs/measurements/2026-11-13-eq-{before,after}.json`, from the Stage 1.7 version of
`scripts/measure_eq.py`, in the history before commit ec2d2d3):
- **Labelled set:** 25/38, then 38/38.
- **Held-out probes:** 10/24, then 20/24.
