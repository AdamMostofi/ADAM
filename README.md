# ADAM
*(First Of It's Kind)*

A neuro-symbolic cognitive architecture that emulates a super-infant AI — starting with foundational logic and reasoning, then learning continuously through teaching and experience. Perfect memory. Cross-domain reasoning. Gets smarter with every interaction.

---

## Vision

Build an AI from the ground up that does NOT rely on memorized knowledge or statistical pattern matching. Instead:

- Starts with **basic and foundational logic, analysis, and reasoning systems** (like a human infant, but super)
- Can be **taught and trained to specialize** — teach it programming, it becomes better each time
- Given documentation (e.g., great white sharks), it **remembers, reasons, thinks, and analyzes** the info
- **Never forgets anything** — photographic/eidetic memory without human degradation
- **Continuously forges connections** between different ideas and concepts
- **Gets better and more in tune with the user** every time it runs

### What's Secured
- **Ear:** Needle 2 (45M params, 28MB RAM) — structured intent extraction
- **Mouth:** Tiny-LLM / micro-decoder (~15MB RAM) — persona-formatted output

### What Needs Building
- **Logical Kernel** — reasoning engine (deduction, induction, analogy, contradiction resolution)
- **Program Synthesis Loop** — compiles successful reasoning traces into reusable macro-rules
- **Belief Tape** — working memory with confidence scores and epistemic sources
- **EQ Subsystem** — cognitive appraisal theory for emotional intelligence
- **Memory System** — perfect recall + cross-domain connection graph
- **Continuous Learning** — organic skill acquisition (not prompt engineering loops)

---

## Architecture

```
[ User Input ]
      |
      v
[ Ear: Needle 2 ] --> structured intent (JSON)
      |
      v
[ Belief Tape ] --> working memory, session state
      |
      v
[ Logical Kernel ] <---> [ Memory System ]
      |                         ^
      v                         |
[ EQ Subsystem ] ---+         |
      |              |         |
      v              v         |
[ Mouth: Tiny-LLM ] <-- [ Learning Engine ]
```

**Total RAM footprint: ~45MB for Ear + Mouth. Kernel + Memory run in Python with minimal overhead.**

---

## Phased Roadmap

### V0.1 — Research & Specification (this document)
- Meta AI's neuro-symbolic proposal analyzed
- Needle 2 + Tiny-LLM micro-architecture identified
- Cognitive architecture design finalized

### V0.2 — Logical Kernel (Weeks 1-3)
- Rule engine: modus ponens, transitivity, syllogism
- Knowledge graph via `networkx`
- Inference engine: deduction, induction, abduction, analogy
- Contradiction resolver with confidence-based conflict resolution

### V0.3 — Memory System (Weeks 3-5)
- Three-layer storage: exact (SQLite), semantic (ChromaDB), connection graph (NetworkX)
- Perfect recall with automatic cross-referencing
- `store()`, `recall()`, `connect()`, `get_context()` operations

### V0.4 — Continuous Learning (Weeks 5-8)
- Pattern extraction from teaching sessions
- Skill compilation into macro-rules
- Cross-domain connection building
- Error correction with confidence updating

### V0.5 — EQ Subsystem (Weeks 8-10)
- User state tracker (goals, emotions, engagement)
- Response adjuster (warmth, directness, depth)
- Baseline learner (topic preferences, knowledge level)

### V0.6 — Interface (Weeks 10-12)
- CLI via `rich` or `textual`
- GUI via `gradio` or `textual`
- Memory browser, skill dashboard, knowledge graph viewer

---

## Starting Primitives (Infant Foundation)

Hardcoded foundational reasoning (refinable through experience, but present from birth):

- **Object permanence** — things exist when not observed
- **Basic causality** — A causes B
- **Temporal ordering** — before, after, during
- **Spatial relations** — inside, outside, near, far
- **Basic set theory** — is-a, has-a, part-of

---

## Technology Stack

| Component | Library |
|-----------|---------|
| Rule engine | Custom + `sympy` |
| Knowledge graph | `networkx` |
| Vector memory | `chromadb` or `faiss-cpu` |
| Exact storage | `sqlite3` |
| Embeddings | `sentence-transformers` (all-MiniLM) |
| CLI | `rich` or `textual` |
| GUI | `gradio` or `textual` |
| Data models | `pydantic` |

---

## Core Data Models

```python
@dataclass
class Fact:
    subject: str
    predicate: str
    object: str
    confidence: float  # 0.0-1.0
    source: str       # "user", "deduced", "inferred", "learned"
    timestamp: float

@dataclass
class Rule:
    premises: list[Fact]
    conclusion: Fact
    strength: float
```

---

## Design Principles

1. **Knowledge lives outside the model weights** — facts are stored, retrieved, and reasoned over — never baked into parameters
2. **Reasoning is deterministic** — no hallucination, no probabilistic guessing
3. **Memory is permanent** — nothing forgotten, everything connected
4. **Learning is organic** — skills compiled from experience, not prompt-engineered
5. **Every conclusion has a trace** — you can ask "how do you know?" and get the full reasoning chain
