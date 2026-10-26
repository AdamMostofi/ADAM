# OpenCog Hyperon — what it does better, what ADAM should adopt

*Analysis against the current ADAM codebase (kernel/, memory/, learning/,
interface/). Scope: identify the genuinely superior ideas, decide adopt /
adapt / skip, and record why. Nothing here proposes removing ADAM's existing
architecture.*

---

## 1. Executive summary

Hyperon is a research platform built around one bet: **represent knowledge,
code, and rules in a single uniform structure (the Atomspace hypergraph) and
give it a language (MeTTa) that can query and rewrite that structure.** Every
other component — PLN, ECAN, MOSES, NARS, PRIMUS — is an algorithm that runs
over that substrate.

ADAM makes the opposite bet: **a small, typed, three-field fact
(`subject, predicate, object`) in SQLite, with hardcoded inference rules in
Python.** That is why ADAM is ~2,200 lines and boots in seconds, and Hyperon is
a research stack that takes real effort to build and operate.

The honest comparison:

| Dimension | Hyperon | ADAM | Who is better |
|---|---|---|---|
| Representation | n-ary weighted hypergraph, code = data | fixed S-P-O triples | Hyperon (flexibility) |
| Inference | PLN (probabilistic), NARS (resource-bounded) | hardcoded forward chaining | Hyperon (theory), ADAM (simplicity) |
| Query | pattern matching + rewriting | SQL lookup + unifier | Hyperon |
| Attention | ECAN built into the atom store | none (now: small bank) | Hyperon |
| Learning | MOSES (evolutionary program search) | proof-pattern extraction | Hyperon (search power) |
| Self-modification | first-class (MeTTa rewrites itself) | none | Hyperon |
| Runtime | Rust core, distributed | Python + SQLite + LanceDB | Hyperon (scale), ADAM (iteration speed) |
| Operability | research build | one `pip install`, one process | ADAM |
| LLM integration | external | first-class (embeddings, chat) | ADAM |

**Verdict:** do not port Hyperon. Adopt four specific ideas that fix real
weaknesses in ADAM, in this order: attention (done), goal-directed proof
(done), declarative rules, n-ary atoms. Skip MeTTa-the-language and a Rust
rewrite for now.

---

## 2. Component by component

### 2.1 Atomspace MetaGraph → `kernel/facts.py`, `kernel/graph.py`, `memory/`

**What Hyperon does.** The Atomspace is a weighted, labelled hypergraph that
holds every kind of knowledge in one shape: declarative, procedural, goals,
attention values, types. Atoms are immutable and content-addressed, so the
same knowledge is never duplicated. The Distributed Atomspace (DAS) shards
that graph across machines and synchronises it.

**ADAM today.** `Fact` is a frozen dataclass with exactly three string terms
plus confidence/source/timestamp. Storage is split three ways: `ExactStore`
(SQLite, verbatim recall), `SemanticIndex` (LanceDB vectors), `ConnectionGraph`
(NetworkX MultiDiGraph). The graph is a *derived view* of the facts, rebuilt
from SQLite on load.

**What is genuinely better in Hyperon**
- **Uniformity.** One atom type means one query language and no impedance
  mismatch between "fact", "rule", and "goal". ADAM needs separate code paths
  for facts (`Fact`), rules (`foundations.py` functions), and skills
  (`Skill` dataclass).
- **N-ary relations.** `(gave Alice book Bob)` is one atom. ADAM needs three
  binary facts plus an event node, or it loses the relation's identity.
- **Content addressing.** Idempotent insertion for free. ADAM dedupes by
  `str(fact)` key, which breaks as soon as terms contain spaces.

**Verdict: ADAPT (later).** Keep SQLite as the durable store; add an
`Atom`-shaped layer above `Fact` rather than replacing it. Concretely:
allow `object` to be a JSON-encoded term list, or add a `terms` column. This
is the single highest-leverage structural change available, but it touches
every subsystem, so it must be a deliberate migration with a compatibility
window — not a hot-patch.

**Do not adopt:** DAS. Distributed sync is a multi-machine problem ADAM does
not have yet. `memory/persistence.py` already gives save/load; revisit when
there is a second process, not before.

---

### 2.2 MeTTa → `kernel/foundations.py`, `kernel/engine.py`, `kernel/prove.py`

**What Hyperon does.** MeTTa is a language where a program *is* a subgraph of
the Atomspace. It combines functional, logic, and process-calculus
programming; it can inspect and rewrite itself at runtime. Rules are data,
so "learning a rule" and "defining a rule" are the same operation.

**ADAM today.** Rules are Python functions in `kernel/foundations.py`
(16 of them: modus ponens, transitivity, De Morgan, …). `InferenceEngine.
_apply_rules_indexed` dispatches on `fact.predicate` with an if-chain, and
`_get_rule_name` maps results back to names. Adding a rule means editing two
Python functions and the index. Learned `Skill` objects are *not* executable —
they are JSON records the engine never consults.

**What is genuinely better in Hyperon**
1. **Rules as data.** A learned skill can become an inference rule without a
   code change. This is exactly the gap in `learning/skill_compiler.py`: it
   compiles skills to JSON and nothing executes them.
2. **Pattern-directed rewriting.** A rule is a pattern with variables, applied
   by unification over the whole store — not a hardcoded if-branch.
3. **Self-modification.** The system can rewrite its own rule set. ADAM's
   `foundations.py` is explicitly immutable by design (Layer 1), which is a
   defensible safety choice, but Layer 2 (learned rules) has no mechanism.
4. **Gradual typing.** MeTTa checks types partially; ADAM has none.

**What is NOT better for ADAM right now**
- **Cost.** A MeTTa interpreter is a language runtime: parser, evaluator,
  type checker, error model, debugger. That is far larger than ADAM's entire
  kernel. It would replace a 350-line engine with a multi-thousand-line
  runtime and a new failure surface.
- **Debuggability.** ADAM's proof traces are plain strings a human can read.
  A rewriting runtime makes "why did this fire" harder, not easier.
- **Ecosystem.** ADAM's rules are Python and can call embeddings, SQLite, the
  LLM. MeTTa rules would need FFI for all of that.

**Verdict: SKIP the language; ADOPT its two mechanisms.**

**(a) Declarative rule registry (Next).** Replace the hardcoded dispatch with
a table of rule objects, keeping the built-ins as the initial entries:

```python
@dataclass(frozen=True)
class Rule:
    name: str
    when: tuple[str, str]          # (trigger predicate, partner predicate)
    apply: Callable[[Fact, Fact], list[Fact]]

RULES = [Rule("modus_ponens", ("implies", "is"), modus_ponens), ...]
```

`Skill` then compiles to a `Rule` and registers in a **Layer 2** table that
`infer()` also scans. `foundations.py` stays immutable — the hardcoded rules
remain the trusted floor. This is additive and testable against the existing
agenda tests.

**(b) Variable-bearing queries (Next).** `kernel/unification.py` already has
`unify` and `find_unifiable` with an occurs check, but nothing exposes them.
Add `engine.query_pattern(subject, predicate, object)` where `?x` terms bind —
the MeTTa `match` operation, minus the language.

**(c) `engine.prove(...)` (Done).** Backward chaining was missing entirely:
the engine could only saturate forward. `kernel/prove.py` now searches from
the goal and returns a readable proof chain without mutating beliefs. That is
the NARS/PLN query discipline applied to ADAM's rule set.

---

### 2.3 PLN → `kernel/contradictions.py`, confidence arithmetic

**What Hyperon does.** Probabilistic Logic Networks attach a truth value
`(strength, confidence)` to every atom, where confidence reflects *amount of
evidence*, not probability. Revision combines independent evidence properly:
two weak independent proofs of the same conclusion raise confidence. Deduction
has a principled formula instead of naive multiplication.

**ADAM today.** One scalar `confidence`. Every rule multiplies confidences
(`modus_ponens`: `p * q`), which conflates "probability of the conclusion" with
"certainty". On a repeated derivation the engine does
`if key not in self.beliefs` — the second, independent proof is **discarded**.
So ADAM systematically under-reports confidence when evidence converges.

**What is genuinely better in Hyperon**
- Truth values distinguish strength from evidence mass.
- Revision: `c = (w1+w2)/(w1+w2+1)` with `w = c/(1-c)` — monotone, bounded,
  and rewards independent confirmation.
- Contradiction handling is graded rather than a boolean flag.

**Verdict: ADAPT (Next, staged).** Do **not** change the rule formulas —
`tests/integration/test_engine_confidence.py` pins `0.9 × 0.9 = 0.81` and
that contract is fine for single-proof chains. Instead:

1. Add `kernel/truth.py` with `TruthValue(strength, confidence)` and PLN
   `revision()` / `deduction()`.
2. Track *evidence count* per belief. When the same fact key is derived again
   from a different support set, apply **revision** to the belief instead of
   dropping the derivation. New fields on `Belief`, not on the frozen `Fact`.
3. Expose `strength` and `confidence` separately in `/api/facts` and the UI.

Acceptance test: deriving `a is c` from two independent paths yields higher
confidence than one path, and never exceeds 1.0.

**Risk:** several existing tests assert exact single-path confidences. Stage
the change so single-path behaviour is byte-identical and only duplicate
derivations change.

---

### 2.4 ECAN → `memory/attention.py` (new)

**What Hyperon does.** The Economic Attention Network treats attention as a
scarce currency inside the atom store. Atoms hold short-term importance (STI)
and long-term importance (LTI); STI decays every tick and is re-earned when an
atom participates in reasoning. Forgetting is economic, not deletion.

**ADAM before today.** `MemorySystem.recall` ranked text matches by insertion
order and semantic matches by cosine only. A fact recalled a hundred times
ranked the same as one never touched. There was no notion of "what is the
system currently thinking about".

**What is genuinely better in Hyperon.** Attention is *first-class in the
store*, not a post-hoc ranking, and the budget is global so everything
competes on one scale.

**Verdict: ADOPT (Done, small).** `memory/attention.py` implements STI/LTI,
decay, and a stable rank; `recall()` now decays, stimulates returned facts, and
orders by attention. Deliberately minimal:

- chisel: in-memory, resets on restart; persist to `facts.metadata` when
  attention must survive sessions.
- Not adopted yet: global budget (STI total capped, weakest atoms forgotten).
  Add when the fact count makes unbounded STI meaningless.

This is the ECAN idea, not ECAN's code. That is the right level for now.

---

### 2.5 MOSES → `learning/pattern_extractor.py`, `learning/skill_compiler.py`

**What Hyperon does.** MOSES is evolutionary program search using estimation
of distribution algorithms: it evolves populations of program trees against a
fitness function, and models the distribution of good programs to propose
better ones.

**ADAM today.** `PatternExtractor` parses proof strings, keys patterns by the
conclusion text, and counts occurrences. `SkillCompiler` stores the result as
JSON with a confidence and usage count. There is no search, no fitness, no
variation, and no execution of learned skills.

**What is genuinely better in Hyperon.** MOSES can discover *programs*, not
just observed patterns, and it optimises a fitness signal instead of counting
repetitions.

**Verdict: ADAPT selectively (Later).**
- Worth borrowing: **fitness-weighted skill quality**. Replace `usage_count`
  with `successes / attempts` (a skill that fires and leads to a verified
  conclusion goes up; a retracted conclusion goes down). That is a one-field
  change and makes `should_use_skill` meaningful.
- Worth borrowing: **variation**. When two skills share premises, propose a
  merged generalised skill and test it — a minimal genetic operator.
- Skip: full EDAs/program-tree evolution. ADAM has no fitness oracle for
  arbitrary programs and no compute budget for a population loop. Revisit only
  if there is a real task distribution to evolve against.

---

### 2.6 NARS → `kernel/engine.py`

**What Hyperon does.** NARS reasons under **insufficient knowledge and
resources**: it does not assume axioms are complete, it revises beliefs as
evidence arrives, and it is explicitly resource-bounded (every inference has a
cost and a budget).

**ADAM today.** `infer(max_iterations=10000)` is resource-bounded in name
only; it saturates until the agenda empties. There is no cost model, no
priority, and no "good enough" answer — a query either finds a belief or does
not.

**What is genuinely better in Hyperon.** Resource-bounded *answering*: stop
when the budget is spent and return the best partial evidence with its
confidence. That is how a real system behaves under load.

**Verdict: ADOPT the discipline (Done + Next).**
- Done: `engine.prove()` answers a specific goal without saturating the whole
  agenda — the query pays for the query, not the closure.
- Next: give `prove()` a **step budget** (already present as `STEP_LIMIT`)
  surfaced in the result, and let `chat()` prefer `prove()` for question-shaped
  intents before falling back to forward `infer()`.

---

### 2.7 PRIMUS → whole-system architecture

**What Hyperon does.** PRIMUS is the umbrella cognitive architecture: a
self-modifying system with perception, goals, attention, learning, and
meta-cognition wired together. It is a design document more than a running
system — Hyperon is the infrastructure built to make it possible.

**ADAM today.** `interface/core.py` is the closest thing to PRIMUS: it wires
`MemorySystem`, `LearningEngine`, `EQEngine`, `Ear`, `Mouth` into one facade.
EQ (emotional state) and `Ear`/`Mouth` (intent/tone) are ADAM's own additions
that Hyperon does not have equivalents for.

**Verdict: SKIP as a blueprint.** PRIMUS is under-specified by its authors'
own admission. Copying its structure would add ceremony without capability.
ADAM's facade is a better fit for its size and has things PRIMUS lacks
(emotional state, LLM I/O).

**One idea worth stealing:** a **goal register**. ADAM processes messages
statelessly per turn. A small persistent goal list (what the user is trying to
achieve across turns) would let `chat()` prioritise recall. Add only when
there is a multi-turn workflow that needs it — not speculatively.

---

## 3. MeTTa vs. ADAM's kernel — the honest comparison

| Question | MeTTa | ADAM kernel |
|---|---|---|
| Can rules be added without editing code? | Yes, rules are atoms | No — edit Python |
| Can the system rewrite its own rules? | Yes | Only Layer-2 would (not built) |
| n-ary relations | Native | No |
| Pattern queries with variables | Native (`match`) | Unifier exists, not exposed |
| Type system | Gradual | None |
| Runtime size | Language runtime | ~350 lines |
| Debuggability of inference | Harder | Plain-string traces |
| Calls Python/LLM/SQL | Via FFI | Native |

**Conclusion.** MeTTa is genuinely better at *representing and rewriting
knowledge*. It is not better at *being embedded in a small Python system*.
The two capabilities that matter to ADAM — declarative rules and pattern
queries — can be had for roughly 100 lines of Python without a language
runtime. Take those; leave the language.

If ADAM ever needs real self-modification, the correct move is still not to
embed MeTTa. It is to make Layer 2 a rule registry with an audit log of every
registered rule and its provenance, so self-modification is reviewable.

---

## 4. Rust — should we?

**Why Hyperon is Rust.** The core (Atomspace, MeTTa evaluator, unification) is
a long-running, concurrent, memory-heavy engine. Rust gives predictable
latency, no GC pauses during inference, safe concurrency across the atom store,
and a single binary for distribution. It is the right choice *for that
workload*.

**ADAM's profile.**
- The kernel is small and not the bottleneck. Chat latency is dominated by
  embedding inference (`fastembed`/ONNX) and the LLM, both of which are already
  native code behind Python bindings.
- `strace`-level optimisation is pointless when a single embed call costs more
  than thousands of rule firings.
- Python is where the LLM, SQLite, NetworkX, LanceDB, and Flask ecosystems are.
  A Rust rewrite would need bindings for all of them or lose them.
- ADAM is operated as one process, one user. There is no concurrency wall.

**Verdict: SKIP a rewrite. Revisit only if profiling proves a kernel hotspot.**

If that day comes, the disciplined move is a **PyO3 extension module** for one
function (the unification/chaining inner loop), keeping the Python API and
tests unchanged — not a reimplementation.

**Do not do this because it is fashionable.** Rust does not make a system more
general; it makes an existing workload faster and safer. ADAM's open problem is
knowledge representation and reasoning quality, not throughput.

---

## 5. Adoption roadmap

### Done in this change
| Item | Where | Test |
|---|---|---|
| ECAN-style attention (STI/LTI, decay, ranking) | `memory/attention.py`, `memory/system.py` | `tests/unit/test_attention.py` |
| Goal-directed backward chaining (NARS/PLN query discipline) | `kernel/prove.py`, `InferenceEngine.prove` | `tests/unit/test_prove.py` |
| Stats surface for deduced facts/contradictions/trace | `interface/core.py`, `/api/stats` | interface tests |
| Phase 14: lazy tabs, aria roles, keyboard nav, graph source colours, source filter/badges | `interface/web/*` | `tests/integration/test_interface.py` |

### Next (high value, contained)
1. **Declarative rule registry + executable skills** — `kernel/rules.py`;
   `SkillCompiler` emits a `Rule`. Layer 1 stays immutable.
2. **Pattern queries** — expose `kernel/unification.py` as
   `engine.query_pattern("?x", "is", "mortal")`.
3. **PLN truth values for duplicate derivations** — `kernel/truth.py` +
   `Belief.evidence`; single-path confidence unchanged.
4. **Fitness-weighted skills** — replace `usage_count`-only quality with
   `successes/attempts`.

### Later (structural, needs a migration plan)
5. **n-ary terms** — `Fact.object` accepts a term list; graph builder handles
   relation nodes. Enables "gave(Alice, book, Bob)" without event-node hacks.
6. **Attention persistence + global budget** — write `attention` into
   `facts.metadata`, cap total STI, forget the weakest.
7. **Goal register** — persistent multi-turn objectives in `interface/core.py`.
8. **Optional PyO3 fast path** — only if profiling justifies it.

### Skip (with reasons)
| Idea | Why skip |
|---|---|
| MeTTa interpreter | Language runtime far larger than the kernel; loses Python/LLM/SQL integration |
| Distributed Atomspace | Single-process system; `persistence.py` already covers save/load |
| MOSES program evolution | No fitness oracle or compute budget for a population loop |
| PRIMUS as architecture | Under-specified; ADAM's facade already fits better |
| Rust rewrite | Kernel is not the bottleneck; would cost the Python ecosystem |
| Replacing SQLite facts | Durability and inspectability are an advantage, not debt |

---

## 6. What we deliberately keep

None of the above removes an existing component. Specifically preserved:

- `kernel/foundations.py` as the immutable Layer 1 rule floor — a safety
  property Hyperon does not offer.
- SQLite verbatim storage (`memory/exact_store.py`) — perfect recall is a
  feature, and Hyperon's in-memory emphasis is the opposite trade.
- Proof chains as human-readable strings — ADAM's debuggability advantage.
- `Ear`/`Mouth`/`EQEngine` — ADAM-specific I/O and affect; Hyperon has no
  equivalent and we are not giving them up.
- The 40K web UI and its vanilla, zero-build stack.

The goal is to make ADAM *more* capable at reasoning without making it *less*
operable. Every adoption above is additive and testable in isolation.
