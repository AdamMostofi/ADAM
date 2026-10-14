# ADAM — Design Document

## Kernel Architecture

### Two-Layer Design

**Layer 1: Immutable Foundation** — hardcoded logical primitives that cannot be changed, only built upon.

**Layer 2: Acquired Logic** — rules the system deduces and learns itself over time.

---

## Layer 1: Foundational Logic (Immutable)

### A. Propositional Logic
- AND / OR / NOT — basic combination
- De Morgan's Laws — NOT over AND/OR
- Double Negation — NOT(NOT P) = P
- Modus Ponens — If P->Q and P, then Q (70% of all reasoning)
- Modus Tollens — If P->Q and not Q, then not P (debugging)
- Disjunctive Syllogism — If A or B and not A, then B (decision making)
- Transitivity for Implication — If P->Q and Q->R, then P->R (chaining rules)
- Conditional Proof — if assuming P leads to Q, then P->Q

### B. Equality & Comparison
- Reflexivity — A = A
- Symmetry — If A = B then B = A
- Transitivity of = — If A = B and B = C then A = C
- Substitution (Leibniz) — If A = B, replace A with B anywhere
- Transitivity of >, <, >= — If A > B and B > C then A > C

### C. Predicate Logic
- Universal Instantiation — If All X are Y, and a is X, then a is Y
- Existential Generalization — If a is X, then there exists X
- Universal Generalization — If it holds for arbitrary c, it holds for all X
- Unification — Does B in fact 1 equal B in fact 2? If yes, link them

### D. Minimal State Logic
- Negation as Failure — If searched tape and didn't find P, assume not P with low confidence
- Contradiction Detection — If tape has P and not P, flag it, don't explode, ask for priority

---

## Layer 2: Acquired Logic (Learned)

| Rule | How Acquired |
|------|-------------|
| Analogy | Pattern match: "A:B :: C:?" — store analogy templates |
| Abduction | Store causal rules, reverse-infer with confidence < 1.0 |
| Relation Composition | When father(A,B) and father(B,C) co-occur, propose grandfather(A,C) |
| Recursive Definitions | Detect self-referential patterns in input |
| Causal Chains | Compose cause facts transitively |
| Quantifier Shifting | Syllogism patterns over sets |
| Meta-Rules (Exception > General) | When contradiction found, mark more specific rule as higher priority |
| Procedure Learning | Extract ordered action sequences from instructional text |

---

## File Structure

```
kernel/
  __init__.py
  facts.py              # Fact, Rule, Belief dataclasses
  engine.py             # Forward-chaining inference engine
  foundations.py        # Layer 1: immutable rules
  acquired.py           # Layer 2: learned rules, grows over time
  graph.py              # Knowledge graph (networkx) - deduced knowledge
  source_graph.py       # Separate graph for book/source material
  contradictions.py     # Confidence-based conflict resolution
  unification.py        # Pattern matching between facts
  abduction.py         # Best-explanation reasoning
  analogy.py            # Cross-domain mapping
```

---

## Two-Graph System

- **graph.py** — "What I have deduced and can reason over" (derived knowledge)
- **source_graph.py** — "What the book actually said" (raw extracted facts with provenance)

Verification chain: `deduced fact → source fact → book passage`

---

## Learning Methodology (Student Model)

### Phase 1: Survey
Scan book structure (chapters, sections, headings). Build table of contents graph.

### Phase 2: Chunk
Split into study units. System determines chunk size by:
- Conceptual density (new terms per section)
- Dependency graph (what must be understood before what)
- Self-test: after reading a chunk, can it answer questions about it?

### Phase 3: Master
For each chunk:
1. Extract key statements → store in source_graph
2. Apply foundational logic → deduce implications → store in graph
3. Generate questions → attempt answers → flag gaps
4. If gaps exist, re-read with focus on gaps

### Phase 4: Connect
After mastering a chunk, connect it to all previously learned chunks. Build cross-references.

### Phase 5: Review
Periodically re-test against earlier chunks. Strengthen or weaken connections based on recall success.

---

## Ontology Formation

### Stage 1: Gödel, Escher, Bach (Hofstadter)
- Extract **ways of thinking**, not factual statements
- Focus on: strange loops, self-reference, isomorphism, formal systems
- Goal: teach the kernel how to think about thinking

### Stage 2: Kitab Al-Shifa (Ibn Sina)
- English translations (user to source)
- Start with logic volumes, then natural philosophy
- Build rich ontology and sage-like reasoning foundation
- Long-term knowledge base, not one-time load

---

## Design Decisions

1. **Reasoning trace output** — system outputs its reasoning chain by default, not only when asked
2. **Mastery assessment** — question-answering (system generates questions, attempts answers, flags gaps)
3. **Confidence decay** — facts not accessed for long periods get slightly lower confidence (not forgotten, just deprioritized)
4. **Reasoning trace storage** — every deduction stores its proof chain for error tracing
5. **Self-model** — kernel maintains model of what it knows and doesn't know; "I don't know" is valid output
6. **Question generation** — system proactively generates questions about knowledge gaps

---

## Cross-Reasoning Capability

The kernel handles:
- Deduction (certain conclusions)
- Induction (pattern generalization)
- Abduction (best explanation)
- Analogical reasoning (cross-domain mapping)
- Chain of thought (multi-step reasoning with visible trace)
- Self-reflection (reasoning about its own reasoning)
