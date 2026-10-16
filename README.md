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

### What's Built
- **Logical Kernel** — 16 foundational rules, O(n) agenda inference, thread-safe, 162 tests passing
- **Memory System** — 3-layer storage (SQLite + LanceDB + NetworkX), semantic search, auto-connection, persistence, 169 tests passing

### What's Built
- **Logical Kernel** — 16 foundational rules, O(n) agenda inference, thread-safe, 162 tests passing
- **Memory System** — 3-layer storage (SQLite + LanceDB + NetworkX), semantic search, auto-connection, persistence, 169 tests passing
- **Continuous Learning** — pattern extraction, skill compilation, cross-domain mapping, error correction, 48 tests passing
- **EQ Subsystem** — cognitive appraisal, response adjustment, baseline learning, manual override, 38 tests passing
- **Interface** — CLI (rich) + Web UI (Flask + custom HTML/JS), 5 tabs (Chat, Knowledge Graph, Memory, Skills, Settings), 19 tests passing

### What Needs Building
- **Ear/Mouth Integration** — Needle 2 + Tiny-LLM (V0.7)
- **Advanced UI Features** — streaming, real-time graph updates, dark/light themes

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

### V0.1 — Research & Specification (Complete)
- Meta AI's neuro-symbolic proposal analyzed
- Needle 2 + Tiny-LLM micro-architecture identified
- Cognitive architecture design finalized

### V0.2 — Logical Kernel (Complete)
- 16 foundational rules: modus ponens, modus tollens, transitivity, subtype_transitivity, is_transitivity, universal_instantiation, existential_generalization, universal_generalization, equality_substitution, disjunctive_syllogism, contradiction_detection, de_morgan_and/or, double_negation, conditional_proof
- Predicate-indexed agenda system for O(n) inference (was O(n^3))
- Thread-safe via RLock
- Knowledge graph with MultiDiGraph (handles multiple edges, cycles, self-loops)
- Contradiction resolver with confidence-based conflict resolution
- Unification with occurs check and confidence-based ranking
- 162 tests passing (unit, integration, stress, fuzz, property-based)
- 3 red-team passes completed

### V0.3 — Memory System (Next)
- Three-layer storage: exact (SQLite), semantic (ChromaDB), connection graph (NetworkX)
- Perfect recall with automatic cross-referencing
- `store()`, `recall()`, `connect()`, `get_context()` operations
- JSON persistence for engine state (save/load with re-derivation)

### V0.4 — Continuous Learning
- Pattern extraction from teaching sessions
- Skill compilation into macro-rules
- Cross-domain connection building
- Error correction with confidence updating

### V0.5 — EQ Subsystem
- User state tracker (goals, emotions, engagement)
- Response adjuster (warmth, directness, depth)
- Baseline learner (topic preferences, knowledge level)

### V0.6 — Interface (Complete)
- CLI via `rich` — interactive REPL with colored output
- Web UI via Flask + custom HTML/JS/CSS — 5 tabs: Chat, Knowledge Graph, Memory, Skills, Settings
- vis.js for interactive knowledge graph visualization
- Full/simple mode toggle (full = kernel + memory + learning + EQ, simple = memory + EQ only)
- Loading spinner during chat processing
- No auth — localhost only
- 19 tests passing

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
| Rule engine | Custom (16 rules) |
| Inference | Predicate-indexed agenda (O(n)) |
| Thread safety | `threading.RLock` |
| Knowledge graph | `networkx` (MultiDiGraph) |
| Vector memory | `chromadb` or `faiss-cpu` (V0.3) |
| Exact storage | `sqlite3` (V0.3) |
| Embeddings | `sentence-transformers` (all-MiniLM) (V0.3) |
| CLI | `rich` |
| Web UI | Flask + custom HTML/JS/CSS |
| Graph viz | vis.js (CDN) |
| Data models | `dataclasses` |
| Testing | `pytest`, `hypothesis` |

---

## Core Data Models

```python
@dataclass(frozen=True)
class Fact:
    subject: str
    predicate: str
    object: str
    confidence: float  # 0.0-1.0
    source: Source     # "user", "deduced", "inferred", "learned"
    timestamp: float

@dataclass
class Belief:
    fact: Fact
    proof_chain: list[str]
```

---

## Quick Start

### CLI
```bash
python -m interface.cli              # interactive REPL
python -m interface.cli "hello"      # single-shot query
python -m interface.cli --web        # launch web UI
```

### Web UI
```bash
python -m interface.web.app          # starts on http://localhost:7860
```

Open http://localhost:7860 in your browser. 5 tabs: Chat, Knowledge Graph, Memory, Skills, Settings.

---

## Design Principles

1. **Knowledge lives outside the model weights** — facts are stored, retrieved, and reasoned over — never baked into parameters
2. **Reasoning is deterministic** — no hallucination, no probabilistic guessing
3. **Memory is permanent** — nothing forgotten, everything connected
4. **Learning is organic** — skills compiled from experience, not prompt-engineered
5. **Every conclusion has a trace** — you can ask "how do you know?" and get the full reasoning chain
6. **Thread-safe by default** — all mutating operations protected by RLock
7. **O(n) inference** — predicate-indexed agenda system, no redundant re-scanning
