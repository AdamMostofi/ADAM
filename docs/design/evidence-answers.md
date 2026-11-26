# Answers from evidence

**Status:** Current. Stage 4.3, Speak Only the Evidence ([#34](https://github.com/AdamMostofi/ADAM/issues/34)).

**The rule:** ADAM never states a fact it can't back.
- **Every factual sentence has evidence.** It comes from a proof (a belief walked back to the facts it was
  given), or it is a passage quoted exactly from the source library.
- **The evidence goes out with the reply.**
- **No evidence, no answer.** When nothing supports an answer, ADAM says so and asserts nothing.

The code is `interface/evidence.py`; `ADAMCore.chat` calls it after recall and inference.

## The owner's call: phrasing, with zero hallucinations

Decision DS.1 proposed fixed templates for factual answers. The owner rejected templates as too robotic: the
model may phrase, since that is its purpose, but hallucinations must be zero and it must not make up nonsense.

**TinyChat15M was tested first** (2026-11-25, 16 samples at the Mouth's settings):
- **It never restated a fact.** Asked to phrase "Socrates is a man; every man is mortal", it said things like
  "it sounds like a great adventure for you and you to plan for."
- **Its small talk is often nonsense.** Asked how it was, it said things like "can help us understand why
  people would choose to join such a record for phones?"

**So the middle ground is:**
- **Facts are worded from their proofs,** in natural, varied phrasings: "Yes, that's right. Socrates is a man
  and every man is a mortal, so Socrates is a mortal." Each clause says exactly what one fact in the proof
  says. The opener varies by message, and the same message always reads the same way.
- **Passages are quoted exactly,** never paraphrased: "Here's what apology.md says (paragraph 2): '…'"
- **The model speaks only where nothing factual is at stake.** That means chatter: a message that isn't small
  talk or a question, and names nothing ADAM knows.
- **Even there, its text must pass a strict check** (`model_text_is_grounded`):
  - every word is in a small conversational vocabulary (no nouns of the world);
  - in a question back to the user, the user's own words are also allowed;
  - there are no digits, and at most 20 words.

  Of the 16 samples above, the check passed only "what do you think about that?". Anything that fails is
  replaced by a plain reply: "I see. Ask me something and I'll answer from what I know."

## Routing

Routing is deterministic. It doesn't use the Ear (see "The Ear" below). The order:

| Message | Route | Reply |
|---|---|---|
| "hello", "how are you?", "what can you do?" | small talk | a fixed reply (`answer_source: small_talk`) |
| Ends in `?`, or starts with a question word | question | facts, then passages, else nothing |
| "X is Y" with a term ADAM knows | statement | checked against what ADAM knows; never just agreed with |
| Anything else | chatter | the Mouth if its text passes the check (`model`), else a plain reply (`acknowledgement`) |

**Questions over facts.** The words are matched to terms ADAM's beliefs use. Matching ignores articles,
understands simple plurals ("men" is "man", "animals" is "animal"), and joins words into multi-word terms:
- **"Is X Y?"** is tried as membership, subclassing and "is", then as their negations. A proof gives "Yes" or
  "No" with the chain. Without one, the reply is "I don't know. Nothing I know shows whether Socrates is a bird."
- **"What is X?", "Who is X?", "Tell me about X", "What do you know about X?"** list what X is, and what
  belongs to X. Each clause is one proven belief, and "who" lists members first.

**Questions over passages.** These are tried when no proof answers:
- **The search.** The source library's FTS5 search runs over the whole question.
- **The coverage rule.** A passage is cited only if it holds at least two thirds of the question's content
  words, so a passage that merely shares one word isn't offered as an answer.
- **A proof wins.** It always comes before a passage.

**Statements** like "Socrates is a man" are checked:
- "That's right" with the proof when it holds;
- "That doesn't match what I know" with the proof of the opposite;
- otherwise "I can't confirm that".

Chat doesn't store what it is told, as before.

## What can't be answered

- **Defaults are said as probable.** "Tweety is a bird and a bird is typically a flier, so probably Tweety is
  a flier."
- **Conflicts aren't answered from.** A fact in an unresolved conflict, or on the losing side of one
  (`kernel/conflicts.py`), backs nothing, and neither does a proof that rests on one: "My evidence disagrees
  about whether the road is wet, so I won't say either way."
- **The kernel's own terms are never shown or matched.** These are `exists`, `true` and arbitrary instances.
- **Goal-directed proof (`prove()`) runs only while inference has work queued.** Once inference has finished,
  it can find nothing forward inference hasn't (`tests/integration/test_prove_agreement.py`). Otherwise an
  unanswerable question over 60,000 beliefs took 9 s.

## The response

`/api/chat` keeps every key it had and adds two:
- **`answer_source`:** `proof`, `passage`, `no_evidence`, `small_talk`, `model` or `acknowledgement`.
- **`evidence`:** a list of what backs the reply:
  - each proof: `claim`, the `origins` of its given facts, and every `step` (rule, premises, fact);
  - each passage: its source key, name, ordinal, `start`, `end`, `sha256` and text.

## How it is tested

The tests are in `tests/integration/test_evidence_answers.py`:
- **Every factual sentence comes from a proof.** The answer to "Is Socrates mortal?" is checked word for word,
  and so are its steps.
- **A question whose words match no fact verbatim** ("Are men animals?") is answered from a proof.
- **Without evidence, nothing is asserted,** and the Mouth isn't asked.
- **The property test.** Random knowledge bases and questions, 150 cases per run, check that:
  - every proof step is a belief the engine holds and holds actively;
  - every word of a factual reply is a word of its evidence or of the fixed phrasings;
  - a reply without a proof asserts nothing.
- **A Mouth that always lies** ("Socrates is a fish who lives on the moon") never reaches a reply.
- **The model check** is run against the real TinyChat samples.
- **Small talk still works,** and the old `/api/chat` keys are all still there.

## Measured

From `scripts/measure_answers.py` ([raw report](../measurements/2026-11-26-evidence-answers.json)). The knowledge
base has 20,000 individuals in a 3-level taxonomy, which is 60,173 beliefs:

| Question | Median | Slowest |
|---|---|---|
| "Is thing7 a top1?" (derived, yes) | 0.09 ms | 92 ms (the first, which builds the term index) |
| "Is thing7 a leaf8?" (no evidence) | 0.05 ms | 0.17 ms |
| "What is thing7?" | 16 ms | 20 ms |
| A statement | 0.05 ms | 0.15 ms |

The term index is rebuilt only when the number of beliefs changes. A stale index could only miss a word, and
the answer would then be "I don't know"; it can't make ADAM assert anything.

## The Ear

The Ear (Cactus Needle) extracts an intent that chat returns but never used. Routing doesn't use it either,
because the deterministic routes above are exact and testable. Needle costs about 85 MB of the 400 MB budget (101 MB alone, less a 16.5 MB Python baseline)
([memory-budget.md](memory-budget.md)). Its removal is recorded under
[#33](https://github.com/AdamMostofi/ADAM/issues/33) as the owner's call; until then, `intent` stays in the
response unchanged.

## Limits

- **Few question shapes.** "Does X fly?" isn't understood, because no rule links verbs to facts; it gets
  "I won't guess".
- **Passages are matched by words, not meaning.** A question worded differently from its passage may miss
  it.
- **Facts are named as stored.** "Socrates is a mortal" uses the noun form even where English would say
  "mortal".
