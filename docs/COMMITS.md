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

---

# Web UI Overhaul — Warhammer 40K Imperium

AI Elements (`elements.ai-sdk.dev`) is a **React 19 + Next.js + Tailwind 4 +
shadcn/ui** library, deprecated end of November 2026. ADAM's UI is Flask +
vanilla HTML/CSS/JS. Using AI Elements directly would require adding a Node
runtime (RAM cost) and building on a deprecated source.

**Decision:** study each AI Elements component's design, structure and utility,
then rebuild it in vanilla HTML/CSS/JS for the existing Flask stack. Zero RAM
increase, no build step, no deprecation lock-in, fully customizable.

**Aesthetic:** Warhammer 40K *Imperium of Man* — void/steel surfaces, Imperial
gold accents, bone/parchment light theme, gothic display type, subtle
Aquila/skull/vox iconography. Header rank: **PRIMARCH** (above Adeptus, below
the Emperor; *primus* = first, matching "First Of It's Kind").

**Color system:** OKLCH (`oklch(L C H)`) — perceptually uniform lightness,
chroma and hue. Chosen over HSL/hex because equal lightness steps look equally
bright and hue stays consistent across the palette, which suits the flat,
theming-heavy Imperium design.

---

## Phase 0 — Research + design foundation

**Files:** `docs/research/**`, `interface/web/static/fonts/**`,
`interface/web/static/css/tokens.css`, `interface/web/static/css/base.css`,
`interface/web/tests/shot.py`

**Change:**
- Saved all 13 required component sources from the AI Elements GitHub repo
  (`vercel/ai-elements`) into `docs/research/components/` **before the site is
  deprecated**.
- Downloaded Cinzel / Oswald / IBM Plex Mono `woff2` (latin subset) for offline
  use.
- Built `tokens.css` (Imperium palette, light + dark themes) and `base.css`
  (reset, layout, typography).
- Built `tests/shot.py` — a Playwright harness that serves the web root and
  screenshots any test page, so every component is verified visually.

**Alternatives considered:**
- Port AI Elements to React (Next.js/Vite) — adds Node runtime + build step;
  ruled out by the zero-RAM constraint.
- Keep the existing generic dark UI — rejected; no AI-native structure.

---

## Phase 1 — Conversation

**Files:** `interface/web/static/js/components/conversation.js`,
`interface/web/static/css/components.css`,
`interface/web/tests/conversation.html`

**Source:** `conversation.tsx` — scroll container (`role="log"`), auto-scroll,
empty state, scroll-to-bottom button, transcript download.

**Vanilla port:** `Conversation` class. Scroll container with smooth
auto-scroll; empty state ("The vox is silent"); floating scroll button that
appears only when not at the bottom; transcript export as Markdown.

**40K mapping:** empty state "THE VOX IS SILENT"; download = export transcript.

**Verified:** screenshots in both dark and light themes
(`tests/conversation-*.png`).

**Bug fixed:** scroll button initially visible at the bottom — added a
`requestAnimationFrame` sync after construction.

---

## Phase 2 — Message

**Files:** `interface/web/static/js/components/message.js`,
`interface/web/static/css/components.css`,
`interface/web/tests/conversation.html`

**Source:** `message.tsx` — `Message` (user/assistant turn), `MessageContent`
(bubble), `MessageActions` / `MessageAction` (copy/retry/share), `MessageToolbar`.

**Vanilla port:** `Message` class with role label, content slot and action row.
User turns render as a right-aligned steel bubble with an Imperial-gold edge;
assistant turns render full-width with a gold rail and a "MACHINE SPIRIT"
stencil label.

**40K mapping:** user = "VOX TRANSMISSION", assistant = "MACHINE SPIRIT";
actions are ghost icon buttons (copy, retry, share, like, dislike).

**Verified:** screenshots in dark and light themes (`tests/message-*.png`).

---

## Phase 3 — MessageContent (markdown)

**Files:** `interface/web/static/js/components/markdown.js`,
`interface/web/static/css/components.css`,
`interface/web/static/js/lib/marked.min.js`,
`interface/web/tests/conversation.html`

**Source:** `message.tsx` — `MessageResponse` renders markdown via *Streamdown*
(GFM, math, code, streaming).

**Vanilla port:** `markdownToNode(text)` — `marked.js` (vendored, v12) parses
markdown; a small allowlist sanitizer strips `<script>`/`<iframe>`/forms,
`on*` handlers and non-http(s) URLs before inserting HTML. Styled headings,
code blocks, tables, lists and blockquotes in the Imperium theme.

**40K mapping:** gold headings with rules, gold-edged code blocks, gold list
markers, gold blockquotes.

**Why vendored instead of CDN:** keeps the UI offline-safe (USB deployment goal)
and version-pinned.

**Verified:** dark and light screenshots (`tests/markdown-*.png`).

---

## Phase 4 — PromptInput

**Files:** `interface/web/static/js/components/prompt-input.js`,
`interface/web/static/css/components.css`,
`interface/web/tests/conversation.html`

**Source:** `prompt-input.tsx` (core: `PromptInput`, `PromptInputTextarea`,
`PromptInputSubmit`; attachments/screenshot tooling omitted as out of scope).

**Vanilla port:** `PromptInput` class. Auto-resizing `<textarea>` (capped at
220 px), gold submit button, Enter-to-send / Shift+Enter for newline, and a
`ready`/`streaming` status that disables submit while the Machine Spirit
answers.

**40K mapping:** field is a steel vox channel with a gold rail; submit is a
gold arrow. Placeholder "Open a vox channel…".

**Verified:** dark and light screenshots (`tests/prompt-*.png`).

---

## Phase 5 — Shimmer / Loader

**Files:** `interface/web/static/js/components/shimmer.js`,
`interface/web/static/css/components.css`,
`interface/web/tests/conversation.html`

**Source:** `shimmer.tsx` (text shimmer) + a cogitator spinner.

**Vanilla port:** `Shimmer` (animated gold gradient sweep across text via
`background-clip:text`), `Loader` (spinning cog + stencil label), and
`ThinkingIndicator` (dashed cogitator panel with shimmer). All CSS animations,
`prefers-reduced-motion` safe.

**40K mapping:** shimmer reads "The Machine Spirit deliberates"; loader "The
cogitator hums…".

**Verified:** dark and light screenshots (`tests/shimmer-*.png`).

---

## Phase 6 — Suggestion

**Files:** `interface/web/static/js/components/suggestion.js`,
`interface/web/static/css/components.css`,
`interface/web/tests/conversation.html`

**Source:** `suggestion.tsx` — `Suggestions` (horizontal scrollable row) +
`Suggestion` (clickable chip).

**Vanilla port:** `Suggestions` labelled row + `Suggestion` chip buttons.
Clicking a chip emits its text (wired to pre-fill the vox channel in the demo).

**40K mapping:** label "SANCTIONED INQUIRIES"; chips are steel pills with a gold
hover.

**Verified:** dark and light screenshots (`tests/suggestion-*.png`).

---

## Phase 7 — ModelSelector

**Files:** `interface/web/static/js/components/model-selector.js`,
`interface/web/static/css/components.css`,
`interface/web/tests/conversation.html`

**Source:** `model-selector.tsx` — dialog with model + effort pickers.

**Vanilla port:** simplified to a segmented cogitator-mode control
(`full` / `simple`), since ADAM has one model and a mode toggle rather than a
model marketplace.

**40K mapping:** label "COGITATOR MODE"; active option is gold-rimmed.

**Verified:** dark and light screenshots (`tests/model-*.png`).

---

## Phase 8 — Reasoning

**Files:** `interface/web/static/js/components/reasoning.js`,
`interface/web/static/css/components.css`,
`interface/web/tests/conversation.html`

**Source:** `reasoning.tsx` — collapsible panel, auto-opens while streaming,
closes when done, with a duration readout.

**Vanilla port:** `Reasoning` class with `start()` / `stop()` (duration timer),
`setOpen()`, `setContent()`. Collapse uses the `grid-template-rows: 0fr → 1fr`
technique (smooth, no JS height math).

**40K mapping:** trigger "MACHINE DELIBERATION" with a spinning cog; content is
a mono kernel trace / EQ appraisal.

**Verified:** collapsed + open screenshots (`tests/reasoning-*.png`).

---

## Phase 9 — Sources

**Files:** `interface/web/static/js/components/sources.js`,
`interface/web/static/js/components/message.js`,
`interface/web/static/css/components.css`,
`interface/web/tests/conversation.html`

**Source:** `sources.tsx` — collapsible citation list with a count trigger.

**Vanilla port:** `Sources` (labelled, collapsible, count) + `Source` cards.
For ADAM, sources are the memory "vaults" recalled for a turn.

**40K mapping:** trigger "ARCHIVED DATA · N vaults"; cards are steel with a
gold rail and a vault icon.

**Bugs fixed while wiring:**
- `Message.setContent([a, b])` previously stringified arrays — now spreads them.
- `Sources` lost its `defaultOpen` when constructed empty (sources added after
  init) — `add()` now restores the default-open state.

**Verified:** dark and light screenshots (`tests/sources-*.png`).

---

## Phase 10 — Tool

**Files:** `interface/web/static/js/components/tool.js`,
`interface/web/static/css/components.css`,
`interface/web/tests/conversation.html`

**Source:** `tool.tsx` — collapsible tool call with a status badge, a
*Parameters* block and a *Result*/*Error* block.

**Vanilla port:** `Tool` class with `setName`, `setState` (pending / running /
completed / error), `setInput`, `setOutput`, `setError`.

**40K mapping:** "RITE: <name>"; running badge pulses gold, completed is gold,
error is crimson; params/result are gold-railed code blocks.

**Verified:** dark and light screenshots (`tests/tool-*.png`).

---

## Phase 11 — Task

**Files:** `interface/web/static/js/components/task.js`,
`interface/web/static/css/components.css`,
`interface/web/tests/conversation.html`

**Source:** `task.tsx` — collapsible step list (`TaskTrigger` / `TaskContent` /
`TaskItem`).

**Vanilla port:** `Task` class with `add({ title, status })` and
`setStatus(index, status)`. For ADAM these are the learning directives
(extract pattern → compile rule → link domains).

**40K mapping:** trigger "DIRECTIVES" with a `done/total` counter; completed
steps get a gold tick, running steps pulse, pending steps stay hollow.

**Verified:** dark and light screenshots (`tests/task-*.png`).

---

## Phase 12 — Fake streaming reveal

**Files:** `interface/web/static/js/components/reveal.js`,
`interface/web/static/css/components.css`,
`interface/web/tests/conversation.html`

**Source:** n/a — AI Elements streams for real via the AI SDK; ADAM keeps
full responses.

**Change:** `Reveal` class renders the complete markdown, then progressively
un-hides word tokens with a gold caret (`word` / `letter` / `line` modes).
Pure CSS/JS — no network, no RAM cost. Honours `prefers-reduced-motion`.

**40K mapping:** gold blinking caret; words fade in as the Machine Spirit
"speaks".

**Verified:** screenshots captured mid-reveal (`tests/reveal-early.png`) and
after completion.

---

## Commit 3 — Fix Mouth model path + prompt format

**Files:** `interface/mouth.py`, `tests/integration/test_ear_mouth.py`

**Bug 1 — wrong default model path.** `_DEFAULT_MODEL` used two `..` from
`interface/`, resolving to `~/models/TinyChat15M.gguf` instead of
`ADAM/models/TinyChat15M.gguf`. Any default `Mouth()` raised
`FileNotFoundError`. Fixed by using one `..`.

**Bug 2 — mismatched prompt format.** TinyChat15M was trained on Llama-2
`[INST]...[/INST]` chat format, but the Mouth sent a custom
`[PARAMS]/[RESPONSE]/[OUTPUT]` prompt. Switched to the native chat format so
responses are relevant.

**Verified:** `Mouth().format_response("hello", ...)` now returns coherent text
(verified live against `llama-server`), replacing the earlier gibberish from
the abandoned `sshleifer/tiny-gpt2` placeholder.

**Theory:** a conversational model must receive prompts in the format it was
trained on; otherwise output is coherent but off-topic.

### Next candidates (not yet applied)

- Replace LanceDB with numpy cosine-search over SQLite → saves ~100 MB.
- Load the ONNX model directly with onnxruntime (skip fastembed wrapper) →
  saves ~40 MB.
- Use a pure-numpy embedder (TF-IDF / hashing) → saves ~200 MB but lowers
  semantic quality.
