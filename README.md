# ADAM
*(First Of It's Kind)*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-310%20passing-brightgreen.svg)]()
[![Version](https://img.shields.io/badge/version-V0.7-blue.svg)]()

A neuro-symbolic cognitive architecture that emulates a super-infant AI — starting with foundational logic and reasoning, then learning continuously through teaching and experience. Perfect memory. Cross-domain reasoning. Gets smarter with every interaction.

---

## Architecture Overview

<p align="center">
  <img src="https://img.shields.io/badge/Architecture-Neuro--Symbolic-purple.svg" />
</p>

**Pipeline:** `User Input → Ear (Needle 2) → ADAM Core → Mouth (TinyChat15M) → Response`

**ADAM Core = 4 subsystems:**
- **Logical Kernel** (V0.2) — 16 foundational rules, O(n) inference
- **Memory System** (V0.3) — SQLite + LanceDB + NetworkX
- **Continuous Learning** (V0.4) — pattern extraction, skill compilation
- **EQ Subsystem** (V0.5) — cognitive appraisal, response adjustment

**Interface** (V0.6) — CLI (rich) + Web UI (Flask)
**Ear/Mouth** (V0.7) — Needle 2 (45M) + TinyChat15M (15M)

---

## Quick Start

### One-Command Install

```bash
git clone https://github.com/AdamMostofi/ADAM.git
cd ADAM
./install.sh
```

### Manual Start

```bash
# CLI
python -m interface.cli              # interactive REPL
python -m interface.cli "hello"      # single-shot query
python -m interface.cli --web        # launch web UI

# Web UI
python -m interface.web.app          # http://localhost:7860
```

---

## Versions

### V0.2 — Logical Kernel
16 foundational rules, predicate-indexed agenda inference (O(n)), thread-safe.
- [Diagram](docs/diagrams/kernel.html)

### V0.3 — Memory System
3-layer storage: SQLite (exact), LanceDB (semantic), NetworkX (graph). Perfect recall, auto-connection, persistence.
- [Diagram](docs/diagrams/memory.html)

### V0.4 — Continuous Learning
Pattern extraction (Popper), skill compilation (HERAKLES), cross-domain mapping (Gentner SMT), error correction (AGM).
- [Diagram](docs/diagrams/learning.html)

### V0.5 — EQ Subsystem
Scherer's Component Process Model. Primary/secondary appraisal, response adjustment, baseline learning, manual override.
- [Diagram](docs/diagrams/eq.html)

### V0.6 — Interface
CLI (rich REPL) + Web UI (Flask, 5 tabs: Chat, Knowledge Graph, Memory, Skills, Settings). vis.js graph visualization.
- [Diagram](docs/diagrams/interface.html)

### V0.7 — Ear/Mouth
Needle 2 (45M params, 28MB RAM) for structured intent extraction. TinyChat15M (15M params) for persona-formatted responses.
- [Diagram](docs/diagrams/ear-mouth.html)

---

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.10+ |
| Inference | Custom predicate-indexed agenda (O(n)) |
| Vector DB | LanceDB |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Graph | NetworkX (MultiDiGraph) |
| Exact storage | SQLite |
| Ear | Needle 2 (Cactus Compute) |
| Mouth | TinyChat15M (transformers) |
| CLI | rich |
| Web UI | Flask + custom HTML/JS/CSS |
| Graph viz | vis.js |
| Models | dataclasses, Pydantic |
| Testing | pytest, hypothesis |

---

## Project Structure

```
ADAM/
├── kernel/                 # Logical Kernel (V0.2)
│   ├── engine.py           # InferenceEngine (O(n) agenda)
│   ├── foundations.py      # 16 immutable rules
│   ├── graph.py            # KnowledgeGraph (MultiDiGraph)
│   ├── contradictions.py   # ContradictionResolver
│   ├── unification.py      # Pattern matching
│   └── facts.py            # Fact, Belief dataclasses
├── memory/                 # Memory System (V0.3)
│   ├── system.py           # MemorySystem API
│   ├── exact_store.py      # SQLite + JSON
│   ├── semantic_index.py   # LanceDB embeddings
│   ├── connection_graph.py # NetworkX auto-connection
│   └── persistence.py      # save/load
├── learning/               # Continuous Learning (V0.4)
│   ├── engine.py           # LearningEngine API
│   ├── pattern_extractor.py
│   ├── skill_compiler.py
│   ├── cross_domain.py
│   ├── error_correction.py
│   └── eq/                 # EQ Subsystem (V0.5)
│       ├── engine.py       # EQEngine API
│       ├── user_state.py
│       ├── appraiser.py
│       ├── adjuster.py
│       ├── baseline.py
│       └── manual_override.py
├── interface/              # Interface (V0.6) + Ear/Mouth (V0.7)
│   ├── core.py             # ADAMCore facade
│   ├── cli.py              # rich CLI
│   ├── ear.py              # Needle 2 wrapper
│   ├── mouth.py            # TinyChat15M wrapper
│   └── web/                # Flask web UI
│       ├── app.py
│       ├── static/
│       └── templates/
├── docs/
│   ├── diagrams/           # Architecture diagrams (HTML+SVG)
│   └── design/             # Design documents
├── tests/                  # 310 tests
├── install.sh              # One-command installation
├── requirements.txt
└── LICENSE                 # MIT
```

---

## Core Data Models

```python
@dataclass(frozen=True)
class Fact:
    subject: str
    predicate: str
    object: str
    confidence: float  # 0.0-1.0
    source: Source     # user, deduced, inferred, learned
    timestamp: float

@dataclass
class Belief:
    fact: Fact
    proof_chain: list[str]
```

---

## Design Principles

1. **Knowledge lives outside the model weights** — facts stored, retrieved, reasoned over — never baked into parameters
2. **Reasoning is deterministic** — no hallucination, no probabilistic guessing
3. **Memory is permanent** — nothing forgotten, everything connected
4. **Learning is organic** — skills compiled from experience, not prompt-engineered
5. **Every conclusion has a trace** — ask "how do you know?" and get the full reasoning chain
6. **Thread-safe by default** — all mutating operations protected by RLock
7. **O(n) inference** — predicate-indexed agenda system, no redundant re-scanning

---

## Future Roadmap

### V0.8 — Repo Overhaul (Current)
- Professional README with badges and structure
- One-command installation (`install.sh`)
- Architecture diagrams for all versions
- MIT license
- USB deployment guide
- Agent clones architecture

### V0.9 — USB Deployment
- Portable: runs from USB on any computer
- Uses host CPU/RAM/GPU only
- No local installation required
- Self-contained with all models + runtime

### V1.0 — Agent Clones
- Specialized clones of ADAM core
- Each clone focused on specific domain/task
- Core has full oversight into all clones
- Bidirectional knowledge transfer:
  - Clone learns → core absorbs new info/skills
  - Core teaches → clone benefits from accumulated knowledge
- Double-progress: learning speed increases with each clone

### V1.1 — Continuous Optimization
- Custom everything for speed + quality
- Profile-guided optimization
- Hardware-specific tuning
- Reduced latency, improved responses

---

## Tests

```bash
python -m pytest tests/ -v
# 310 passed
```

---

## License

[MIT](LICENSE)
