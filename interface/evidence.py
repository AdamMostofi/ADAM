"""Answers from evidence only (Stage 4.3, #34, "Speak Only the Evidence").

**The rule: ADAM never states a fact it can't back.** Every factual sentence in a reply comes from a proof
(a belief walked back to the facts it was given) or is a passage quoted exactly from the source library, and
the evidence goes out with the reply. When nothing supports an answer, ADAM says so and asserts nothing.

**Who words what** (the owner's call, 2026-11-25: the model may phrase, but with zero hallucinations):
- **Facts are worded here,** from the proof's steps, with a few phrasings so replies don't all read the same.
  TinyChat15M was asked to phrase proofs, and never once restated them (2026-11-25, 16 samples: it answered
  "it sounds like a great adventure for you and you to plan for"), so it isn't given facts to word.
- **Passages are quoted,** never paraphrased.
- **The model speaks only where nothing factual is at stake**: chatter that isn't a question and names
  nothing ADAM knows. Even there its text is shown only if it passes `model_text_is_grounded`: no word
  beyond a small conversational vocabulary (the user's own words are allowed in a question back to them),
  no digits, short. Anything else is dropped for a plain reply.

**Routing is deterministic** and doesn't use the Ear: a message is small talk, a question (over facts, then
passages), a statement (checked against what ADAM knows), or chatter.
"""
from __future__ import annotations

import hashlib
import re
import weakref
from dataclasses import dataclass, field

from kernel.defaults import DEFAULT_RULE_NAMES
from kernel.foundations import ARBITRARY_PREFIX, NOT_PREFIX

Key = tuple[str, str, str]

# answer_source values (additive in /api/chat)
PROOF, PASSAGE, NO_EVIDENCE, SMALL_TALK, MODEL, ACKNOWLEDGEMENT = (
    "proof", "passage", "no_evidence", "small_talk", "model", "acknowledgement")

_ARTICLES = {"a", "an", "the"}
_COPULAS = {"is", "are", "was", "were"}
_STOP = _ARTICLES | _COPULAS | {
    "what", "who", "whom", "which", "where", "when", "why", "how", "do", "does", "did", "can", "could", "would",
    "should", "will", "of", "in", "on", "at", "to", "for", "by", "with", "about", "from", "and", "or", "it", "its",
    "this", "that", "these", "those", "be", "been", "me", "you", "i", "my", "your", "tell", "say", "says", "said",
    "know", "there", "any", "some", "according", "has", "have", "had", "not", "no", "yes"}
_QUESTION_START = {"what", "who", "whom", "which", "where", "when", "why", "how", "is", "are", "was", "were",
                   "do", "does", "did", "can", "could", "would", "should", "will", "tell", "explain", "describe"}
_WORD = re.compile(r"[\w'-]+", re.UNICODE)

# Words the model may use on its own: conversation, not content.
CONVERSATIONAL = frozenset("""
a about after again agree ah all also always am an and any anything are as ask at be because been before being
both but by can can't could did didn't do does doesn't doing don't else enough even ever every for from fun get
glad go going good got great had has have having he hear heard her here hey hi him his how i i'd i'll i'm i've if
in indeed interesting is isn't it it's its just keep kind know let let's like little lot make maybe me mean more
most much my nice no not nothing now of oh ok okay on one or other our out over please pleased really right said
same say see seems she should so some something sorry sound sounds still such sure tell than thank thanks that
that's the their them then there these they thing things think this those though to today too try understand up
us very want was way we well were what what's when where which while who why will wish with wonder wonderful
would wow yeah yes yet you you're your yours
""".split())
_MAX_MODEL_WORDS = 20

_YES = ("Yes.", "Yes, that's right.", "That's right.", "Yes, it follows.")
_NO = ("No.", "No, it isn't so.", "Actually, no.")
_CONFIRM = ("That's right.", "Yes, I know.", "That matches what I know.")
_CONTRADICT = ("That doesn't match what I know.", "Actually, no.", "I have it the other way.")
_PASSAGE = ("Here's what {name} says (paragraph {n}):", "From {name}, paragraph {n}:", "{name} has this, in paragraph {n}:")
_ACK = ("I see.", "Okay.", "Noted.", "Got it.")
_SORRY = ("Sorry, that's frustrating.", "Sorry about that.", "Sorry, I know this isn't going well.")
_INVITE = ("Ask me something and I'll answer from what I know.", "If you have a question, I'll answer from what I know.",
           "Ask me a question, and I'll tell you what I can back up.")


@dataclass
class Answer:
    text: str
    answer_source: str
    evidence: list[dict] = field(default_factory=list)


# ------------------------------------------------------------ words
def _pick(options: tuple[str, ...], seed: str) -> str:
    """A phrasing chosen by the message, so the same message reads the same way (and tests are stable)."""
    return options[int.from_bytes(hashlib.sha256(seed.encode()).digest()[:4], "big") % len(options)]


def words(text: str) -> list[str]:
    return [w.lower().strip("'-") for w in _WORD.findall(text) if w.strip("'-")]


def _norm(term: str) -> str:
    return " ".join(term.replace("_", " ").lower().split())


def _singulars(word: str) -> list[str]:
    irregular = {"men": "man", "women": "woman", "people": "person", "children": "child", "mice": "mouse",
                 "geese": "goose", "feet": "foot", "teeth": "tooth"}
    out = [word]
    if word in irregular:
        out.append(irregular[word])
    if word.endswith("ies") and len(word) > 4:
        out.append(word[:-3] + "y")
    if word.endswith("es") and len(word) > 3:
        out.append(word[:-2])
    if word.endswith("s") and not word.endswith("ss") and len(word) > 2:
        out.append(word[:-1])
    return out


_INTERNAL = {"true", "exists"}


def internal(term: str) -> bool:
    """The kernel's own machinery (the "exists" and "true" terms, arbitrary instances): never shown or matched."""
    return term in _INTERNAL or term.startswith(ARBITRARY_PREFIX)


class Terms:
    """The terms ADAM's beliefs use, found from the words of a message."""

    def __init__(self, engine):
        self.by_norm: dict[str, str] = {}
        self.individuals: set[str] = set()
        self.classes: set[str] = set()
        for s, p, o in list(engine.beliefs):
            for t in (s, o):
                if not internal(t):
                    self.by_norm.setdefault(_norm(t), t)
            if p in ("instance_of", "not_instance_of"):
                self.individuals.add(s)
                self.classes.add(o)
            elif p == "subclass_of":
                self.classes.update((s, o))
        self.individuals -= self.classes

    def resolve(self, phrase: list[str]) -> str | None:
        while phrase and phrase[0] in _ARTICLES:
            phrase = phrase[1:]
        if not phrase:
            return None
        for last in _singulars(phrase[-1]):
            found = self.by_norm.get(" ".join([*phrase[:-1], last]))
            if found is not None:
                return found
        return None

    def split(self, rest: list[str]) -> tuple[str | None, str | None, list[str], list[str]]:
        """The best split of `rest` into two known terms: (left, right, left words, right words). When no split
        resolves both, the split that resolves the most words, with None for the side it can't resolve."""
        best = (None, None, rest, [])
        best_score = -1
        for i in range(1, len(rest)):
            left, right = self.resolve(rest[:i]), self.resolve(rest[i:])
            score = (left is not None) * i + (right is not None) * (len(rest) - i) + 100 * (left is not None and right is not None)
            if score > best_score:
                best, best_score = (left, right, rest[:i], rest[i:]), score
        return best


_TERMS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def terms_of(engine) -> Terms:
    """The engine's terms, rebuilt only when its beliefs change in number. A stale index could only miss a
    word (an answer of "I don't know"); it can't make ADAM assert anything, since every fact is checked
    against the engine itself."""
    size = len(engine.beliefs)
    cached = _TERMS.get(engine)
    if cached is None or cached[0] != size:
        cached = (size, Terms(engine))
        _TERMS[engine] = cached
    return cached[1]


def term_words(term: str) -> str:
    """A term as words: underscores become spaces, "not:x" reads "not x", "arbitrary_x" reads "any x"."""
    t = term
    if t.startswith(NOT_PREFIX):
        return "not " + term_words(t[len(NOT_PREFIX):])
    if t.startswith(ARBITRARY_PREFIX) and len(t) > len(ARBITRARY_PREFIX):
        return "any " + term_words(t[len(ARBITRARY_PREFIX):])
    return t.replace("_", " ")


def _article(phrase: str) -> str:
    return ("an " if phrase[:1].lower() in "aeiou" else "a ") + phrase


class Wording:
    def __init__(self, terms: Terms):
        self.terms = terms

    def name(self, term: str) -> str:
        text = term_words(term)
        return text[:1].upper() + text[1:] if term in self.terms.individuals else text

    def clause(self, key: Key) -> str:
        """One fact as a clause: exactly what the fact says, in words."""
        s, p, o = key
        S, O = self.name(s), self.name(o)
        if p == "instance_of":
            return f"{S} is {_article(O)}"
        if p == "not_instance_of":
            return f"{S} isn't {_article(O)}"
        if p == "subclass_of":
            return f"every {S} is {_article(O)}"
        if p == "is":
            return f"{S} is true" if o == "true" else f"{S} is {O}"
        if p == "not_is":
            return f"{S} isn't true" if o == "true" else f"{S} isn't {O}"
        if p == "implies":
            return f"if {S}, then {O}"
        if p == "equals":
            return f"{S} is the same as {O}"
        if p == "typically":
            return f"{_article(S)} is typically {_article(O)}"
        if p == "typically_not":
            return f"{_article(S)} typically isn't {_article(O)}"
        return f"{S} {p.replace('_', ' ')} {O}"

    @staticmethod
    def sentence(text: str) -> str:
        text = text.strip()
        return (text[:1].upper() + text[1:]).rstrip(".") + "."

    @staticmethod
    def join(clauses: list[str]) -> str:
        if len(clauses) <= 2:
            return " and ".join(clauses)
        return ", ".join(clauses[:-1]) + ", and " + clauses[-1]

    def chain(self, steps: list[tuple[str | None, tuple[Key, ...], Key]]) -> str:
        """A proof as sentences, premises first: "A, and B, so C." Each clause is one step's fact."""
        givens = [k for rule, _, k in steps if rule is None]
        derived = [(rule, premises, k) for rule, premises, k in steps if rule is not None]
        if not derived:
            return self.sentence(self.clause(givens[-1]))
        said: set[Key] = set()
        sentences = []
        order = {"instance_of": 0, "not_instance_of": 0, "is": 1, "not_is": 1}
        for i, (rule, premises, k) in enumerate(derived):
            # The particular before the general: "Socrates is a man, and every man is a mortal".
            new = sorted((p for p in premises if p not in said and p in givens), key=lambda p: order.get(p[1], 2))
            said.update(new)
            so = ("so probably " if rule in DEFAULT_RULE_NAMES else "so ") + self.clause(k)
            if new:
                start = ("and since " if i else "") + self.join([self.clause(p) for p in new])
                sentences.append(self.sentence(f"{start}, {so}"))
            else:
                sentences.append(self.sentence(so))
            said.add(k)
        return " ".join(sentences)


def model_text_is_grounded(text: str, message: str) -> bool:
    """True when the model's text asserts nothing: every word is conversational, or, in a question back to
    the user, one of the user's own words. No digits, at most a couple of short sentences."""
    text = text.strip()
    if not text or any(ch.isdigit() for ch in text):
        return False
    found = words(text)
    if not found or len(found) > _MAX_MODEL_WORDS:
        return False
    own = set(words(message)) if text.endswith("?") else set()
    return all(w in CONVERSATIONAL or w in own for w in found)


# ------------------------------------------------------------ the answerer
class Answerer:
    """Turns a message into a reply backed by evidence. `engine` is ADAM's inference engine; `library` the
    source library or None; `mouth` the Mouth (its `format_response`) or None."""

    def __init__(self, engine, library=None, mouth=None, small_talk=None):
        self.engine = engine
        self.library = library
        self.mouth = mouth
        self.small_talk = small_talk

    def answer(self, message: str, params: dict | None = None, frustrated: bool = False) -> Answer:
        """The reply to `message`. When the user seems frustrated (Stage 4.4), ADAM's own fixed wording for
        what it can't do starts with an apology, and the Mouth isn't used; facts and passages are unchanged."""
        found = self._answer(message, params or {}, frustrated)
        if frustrated and found.answer_source in (NO_EVIDENCE, ACKNOWLEDGEMENT):
            found.text = f"{_pick(_SORRY, message)} {found.text}"
        return found

    def _answer(self, message: str, params: dict, frustrated: bool) -> Answer:
        self._disputed_keys = None   # conflicts are read once per answer
        reply = self.small_talk(message) if self.small_talk else None
        if reply is not None:
            return Answer(reply, SMALL_TALK)
        ws = words(message)
        if not ws:
            return Answer(_pick(_INVITE, message), ACKNOWLEDGEMENT)
        terms = terms_of(self.engine)
        wording = Wording(terms)
        question = message.strip().endswith("?") or ws[0] in _QUESTION_START
        if question:
            found = self._fact_question(ws, terms, wording, message)
            if found is not None and found.answer_source == PROOF:
                return found
            passage = self._passage(message)
            if passage is not None:
                return passage
            if found is not None:
                return found
            return Answer(self._nothing(ws, terms), NO_EVIDENCE)
        statement = self._statement(ws, terms, wording, message)
        if statement is not None:
            return statement
        if frustrated:   # no small-talk chatter from the Mouth at a frustrated user
            return Answer(_pick(_INVITE, message), ACKNOWLEDGEMENT)
        return self._chatter(message, params)

    # ---------------------------------------------------- facts
    def _believed(self, s: str, p: str, o: str) -> list | None:
        """Steps of an active belief, else of a strict proof; None if neither holds.

        A belief that is defeated or contested (kernel/conflicts.py) is never answered from: the proof
        fallback runs only for goals the engine holds no belief about at all (inference not reached yet), and
        every given fact a proof starts from must itself be active."""
        steps = None
        if self.engine.query(s, p, o):
            explained = self.engine.explain(s, p, o)
            if explained:
                steps = [(None if d is None else d.rule, () if d is None else tuple(d.premises), k)
                         for k, d in explained]
        elif not self.engine.query(s, p, o, include_inactive=True) and (self.engine.agenda or not self.engine.saturated):
            # Goal-directed proof finds nothing forward inference hasn't once inference has finished (they use the
            # same rules: tests/integration/test_prove_agreement.py), so it only runs while work is still queued.
            found = self.engine.proof_steps(s, p, o)
            if found and all(self.engine.query(*k) for rule, _, k in found if rule is None):
                steps = found
        # A fact in an unresolved conflict, or on the losing side of one, backs nothing (kernel/conflicts.py).
        if steps and any(k in self._disputed() for _, _, k in steps):
            return None
        return steps

    def _disputed(self) -> set[Key]:
        if self._disputed_keys is None:
            self._disputed_keys = set()
            for c in self.engine.conflicts():
                for side in (c.positive, c.negative):
                    if c.winner is None or tuple(c.winner) != tuple(side):
                        self._disputed_keys.add(tuple(side))
        return self._disputed_keys

    def _contested(self, s: str, p: str, o: str) -> bool:
        held = self.engine.query(s, p, o, include_inactive=True)
        return bool(held) and (not self.engine.query(s, p, o)
                               or any((b.fact.subject, b.fact.predicate, b.fact.object) in self._disputed() for b in held))

    def _evidence(self, steps, claim: Key) -> dict:
        origins = self.engine.attribution(*claim)
        return {"type": "proof", "claim": " ".join(claim), "origins": origins,
                "steps": [{"rule": rule or "given", "premises": [" ".join(p) for p in premises],
                           "fact": " ".join(k)} for rule, premises, k in steps]}

    def _yes_no(self, s: str, o: str, wording: Wording, seed: str, as_statement: bool = False) -> Answer:
        """Is s o? Tried as membership, subclassing and plain "is", then their negations."""
        for p in ("instance_of", "subclass_of", "is"):
            steps = self._believed(s, p, o)
            if steps:
                opener = _pick(_CONFIRM if as_statement else _YES, seed)
                return Answer(f"{opener} {wording.chain(steps)}", PROOF, [self._evidence(steps, steps[-1][2])])
        for p in ("not_instance_of", "not_is"):
            steps = self._believed(s, p, o)
            if steps:
                opener = _pick(_CONTRADICT if as_statement else _NO, seed)
                return Answer(f"{opener} {wording.chain(steps)}", PROOF, [self._evidence(steps, steps[-1][2])])
        target = _article(wording.name(o)) if o in wording.terms.classes else wording.name(o)
        claim = f"{'every ' if s in wording.terms.classes else ''}{wording.name(s)} is {target}"
        if any(self._contested(s, p, o) for p in ("instance_of", "subclass_of", "is")):
            return Answer(f"My evidence disagrees about whether {claim}, so I won't say either way.", NO_EVIDENCE)
        lead = "I can't confirm that." if as_statement else "I don't know."
        return Answer(f"{lead} Nothing I know shows whether {claim}.", NO_EVIDENCE)

    def _proven(self, beliefs, evidence: list[dict], limit: int = 6) -> list[Key]:
        """The keys of these beliefs that have a proof, at most `limit`, recording each proof as evidence."""
        found = []
        for belief in beliefs:
            k = (belief.fact.subject, belief.fact.predicate, belief.fact.object)
            if internal(k[0]) or internal(k[2]) or k[0] == k[2]:
                continue
            steps = self._believed(*k)
            if steps:
                found.append((len(steps), k, steps))
        found.sort(key=lambda f: (f[0], f[1]))          # what was given first, then the shortest proofs
        for _, k, steps in found[:limit]:
            evidence.append(self._evidence(steps, k))
        return [k for _, k, _ in found[:limit]]

    def _describe(self, t: str, wording: Wording, members_first: bool = False) -> Answer | None:
        """What ADAM knows about t: what it is and what kinds it belongs to, then what belongs to it. Every
        clause is one proven belief, and its proof goes out as evidence."""
        evidence: list[dict] = []
        about, belongs = [], []
        T = wording.name(t)
        kinds = [wording.name(k[2]) for k in self._proven(self.engine.query(t, "instance_of", None), evidence)]
        if kinds:
            about.append(f"{T} is {wording.join([_article(k) for k in kinds])}")
        supers = [wording.name(k[2]) for k in self._proven(self.engine.query(t, "subclass_of", None), evidence)]
        if supers:
            about.append(f"every {T} is {wording.join([_article(k) for k in supers])}")
        for p in ("is", "not_instance_of", "not_is"):
            about += [wording.clause(k) for k in self._proven(self.engine.query(t, p, None), evidence)]
        members = [wording.name(k[0]) for k in self._proven(self.engine.query(None, "instance_of", t), evidence)]
        if members:
            first, rest = members[0], members[1:]
            more = f", and so {'are' if len(rest) > 1 else 'is'} {wording.join(rest)}" if rest else ""
            belongs.append(f"{first} is {_article(T)}{more}")
        subs = [wording.name(k[0]) for k in self._proven(self.engine.query(None, "subclass_of", t), evidence)]
        if subs:
            belongs.append(wording.join([f"every {s}" for s in subs]) + f" {'is' if len(subs) == 1 else 'are each'} "
                           + _article(T))
        if not about and not belongs:
            return None
        parts = belongs + about if members_first else about + belongs
        return Answer(" ".join(wording.sentence(p) for p in parts), PROOF, evidence)

    def _fact_question(self, ws: list[str], terms: Terms, wording: Wording, seed: str) -> Answer | None:
        lead = ws[0]
        if lead in _COPULAS and len(ws) >= 3:                                   # is socrates mortal?
            s, o, _, _ = terms.split(ws[1:])
            return self._yes_no(s, o, wording, seed) if s and o else None
        about = None
        if lead in ("what", "who") and len(ws) >= 3 and ws[1] in _COPULAS:     # what is a man? who is mortal?
            about = terms.resolve(ws[2:])
        elif ws[:2] == ["tell", "me"] and len(ws) >= 4 and ws[2] == "about":   # tell me about socrates
            about = terms.resolve(ws[3:])
        elif ws[:4] == ["what", "do", "you", "know"] and len(ws) >= 6:         # what do you know about x
            about = terms.resolve(ws[5:])
        if about is None:
            return None
        found = self._describe(about, wording, members_first=lead == "who")
        return found or Answer(f"I know the word “{term_words(about)}”, but nothing I can back up about it.",
                               NO_EVIDENCE)

    def _statement(self, ws: list[str], terms: Terms, wording: Wording, seed: str) -> Answer | None:
        """A claim like "Socrates is a man" is checked against what ADAM knows; it is never just agreed with."""
        for i, w in enumerate(ws):
            if w in _COPULAS and 0 < i < len(ws) - 1:
                s, o = terms.resolve(ws[:i]), terms.resolve(ws[i + 1:])
                if s and o:
                    return self._yes_no(s, o, wording, seed, as_statement=True)
                if s or o:
                    return Answer("I can't confirm that: nothing I know shows it yet.", NO_EVIDENCE)
                return None
        return None

    def _nothing(self, ws: list[str], terms: Terms) -> str:
        unknown = [w for w in ws if w not in _STOP and terms.resolve([w]) is None]
        if unknown and len(unknown) == len([w for w in ws if w not in _STOP]):
            return "I don't know anything about that yet, so I won't guess."
        return "I don't have anything that answers that, so I won't guess."

    # ---------------------------------------------------- passages
    def _passage(self, message: str) -> Answer | None:
        """The best passage, if it holds most of the question's words. It is quoted exactly, with its source."""
        if self.library is None:
            return None
        wanted = {w for w in words(message) if w not in _STOP}
        if not wanted:
            return None
        for p in self.library.search_passages(message, limit=5):
            have = {s for w in words(p.text) for s in _singulars(w)}
            matched = {w for w in wanted if any(s in have for s in _singulars(w))}
            if len(matched) >= max(1, (2 * len(wanted) + 2) // 3):
                lead = _pick(_PASSAGE, message).format(name=p.name, n=p.ordinal + 1)
                return Answer(f"{lead} “{p.text}”", PASSAGE,
                              [{"type": "passage", "source": p.source, "name": p.name, "ordinal": p.ordinal,
                                "start": p.start, "end": p.end, "sha256": p.sha256, "text": p.text}])
        return None

    # ---------------------------------------------------- chatter
    def _chatter(self, message: str, params: dict) -> Answer:
        """Not a question and nothing ADAM can check: the model may reply, if its reply asserts nothing."""
        if self.mouth is not None:
            try:
                text = self.mouth.format_response(message, params, context="")
            except Exception:   # noqa: BLE001 - no Mouth (no server, no model) means the plain reply
                text = ""
            if model_text_is_grounded(text, message):
                return Answer(text, MODEL)
        return Answer(f"{_pick(_ACK, message)} {_pick(_INVITE, message)}", ACKNOWLEDGEMENT)
