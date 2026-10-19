# ADAM — Commit History & Design Decisions

This file documents every logical commit: what changed, why, the alternatives
considered, and the theories behind each decision.

---

## Commit 1 — Gitignore models + commit log

**Files:** `.gitignore`, `docs/COMMITS.md`

**Change:** Added `models/` to `.gitignore`; created this log.

**Reason:** The TinyChat15M GGUF is 98 MB and platform-specific. It is
reproducible from source, so it should not live in git history.

**Alternatives considered:**
- Git LFS — extra tooling, not worth it for one model.
- Commit the binary — bloats history permanently.

---

## Commit 2 — Mouth (TinyChat15M) + Memory embeddings (fastembed/ONNX)

**Files:** `interface/mouth.py`, `interface/core.py`, `memory/semantic_index.py`,
`requirements.txt`, `install.sh`, `tests/integration/test_ear_mouth.py`

### Problem discovered

Running the full test suite crashed WSL repeatedly. Investigation showed
ADAM's pure-Python core is tiny (~30 MB), but the ML dependencies were huge:

| Component | RSS |
|-----------|-----|
| Python + numpy | 27 MB |
| + LanceDB | 128 MB |
| + sentence-transformers (PyTorch) | **442 MB** |
| + Needle 2 (lazy) | ~122 MB |
| llama-server (separate process) | ~62 MB |

**Root cause:** `sentence-transformers` drags in **PyTorch (~216 MB just to
import)**, pushing the embedding stack to 442 MB. The original ~153 MB budget
assumed a lightweight embedding runtime, not PyTorch.

**Separate crash cause:** `pip install llama-cpp-python` compiles llama.cpp from
source. With 12 CPUs, CMake spawned 12 parallel `g++` jobs; each heavy
translation unit needs 3–4 GB → ~18 GB spike on a 7.6 GB VM → OOM reset.

### Decision A — Mouth: llama-server instead of llama-cpp-python

TinyChat15M ships as a llama2.c `.bin`, not PyTorch weights. To run it we need
llama.cpp. Two options:

| Option | RAM | Pros | Cons |
|--------|-----|------|------|
| Build `llama-cpp-python` | compile-time OOM risk | Clean Python API | Source compile crashes WSL |
| Use pre-built `llama-server` | ~62 MB (separate proc) | Already built, zero compile | Separate process + HTTP |

**Chosen:** use the already-built `llama-server` binary as an OpenAI-compatible
HTTP endpoint. `interface/mouth.py` auto-starts it and calls `/v1/completions`.
This needs no compilation and no new Python dependency.

**Theory:** a separate inference process keeps the model's memory out of the
ADAM process and avoids compile-time OOM entirely.

### Decision B — Memory embeddings: fastembed (ONNX) instead of PyTorch

| Option | RAM | Pros | Cons |
|--------|-----|------|------|
| sentence-transformers (torch) | 442 MB | High quality | PyTorch too heavy |
| fastembed (ONNX) | ~267 MB | No torch, drop-in, quantized | Wrapper deps |
| Raw onnxruntime | ~100 MB | Minimal deps | Manual model/tokenizer mgmt |
| sklearn TF-IDF | ~50 MB | Near-zero deps | Lower semantic quality |

**Chosen:** `fastembed` with `BAAI/bge-small-en-v1.5`, which resolves to the
**quantized** ONNX build (`qdrant/bge-small-en-v1.5-onnx-q`, 65 MB on disk).
This removes PyTorch while keeping semantic search quality.

### Result

| Metric | Before | After |
|--------|--------|-------|
| Embedding stack | 442 MB | ~267 MB |
| ADAM core RSS | ~564 MB | **397 MB** |

**Still over the 300 MB target.** Remaining fat: LanceDB (~100 MB) and the
fastembed runtime (~267 MB, of which the 65 MB model loads to ~185 MB RSS).

### Next candidates (not yet applied)

- Replace LanceDB with numpy cosine-search over SQLite → saves ~100 MB.
- Load the ONNX model directly with onnxruntime (skip fastembed wrapper) →
  saves ~40 MB.
- Use a pure-numpy embedder (TF-IDF / hashing) → saves ~200 MB but lowers
  semantic quality.
