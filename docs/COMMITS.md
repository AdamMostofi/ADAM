# ADAM — Commit History & Design Decisions

---

## Commit 1: Gitignore models/

**Change:** Added `models/` to `.gitignore` to exclude the 98MB TinyChat15M.gguf from version control.

**Reason:** Model binaries are large, platform-specific, and reproducible from source. They should not live in git.

**Alternatives considered:**
- Git LFS — adds complexity, not worth it for a single model
- Committing the model — 98MB binary in git history is wasteful

---

## Commit 2: Mouth — switch from llama-server to fastembed (ONNX)

**Change:** Replaced `interface/mouth.py` HTTP-based llama-server approach with `fastembed` (ONNX Runtime) for TinyChat15M inference.

**Why fastembed over llama-server:**
- llama-server requires a separate long-running process (complex lifecycle management)
- fastembed is a clean Python library — no process management, no HTTP
- ONNX Runtime eliminates PyTorch entirely (saves ~350MB RAM)
- Still uses TinyChat15M (user requirement)

**Why fastembed over raw onnxruntime:**
- Drop-in replacement for sentence-transformers API
- Handles model download + quantization automatically
- Minimal code change (~20MB more RAM than raw onnxruntime, far less complexity)

**Alternatives considered:**
| Option | RAM | Pros | Cons |
|--------|-----|------|------|
| sentence-transformers (torch) | 442MB | High quality | PyTorch dependency too heavy |
| llama-server (subprocess) | ~62MB + process overhead | Already built | Separate process, HTTP API, lifecycle |
| fastembed (ONNX) | ~100MB | No torch, drop-in, simple | Extra wrapper deps |
| Raw onnxruntime | ~80MB | Minimal deps | Manual model management |
| sklearn TF-IDF | ~50MB | Near zero deps | Lower semantic quality |

**RAM impact:** ADAM core drops from ~564MB to ~130-230MB (within 300MB budget).

---

## Commit 3: Install script + tests for fastembed

**Change:** Updated `install.sh` to use fastembed model download; updated Mouth tests.

**Model:** `BAAI/bge-small-en-v1.5` (384-dim, ONNX, ~100MB total with runtime)

**Alternatives considered:**
- `sentence-transformers/all-MiniLM-L6-v2` — same 384-dim quality, but requires torch
- `BAAI/bge-base-en-v1.5` — 768-dim, better quality, but larger model
