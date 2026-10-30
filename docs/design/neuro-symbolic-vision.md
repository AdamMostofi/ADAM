# ADAM Neuro-Symbolic Vision

**Status:** Proposed — not implemented  
**Date:** 2026-10-28  
**Repository:** ADAM

This document records the design conversation that produced the current
neuro-symbolic direction for ADAM. It preserves the original prompts, the
architecture response, the user's decisions, the execution plan, and the
follow-up assessment of JEV. It is a design record, not a claim that the
described system already exists.

---

## 1. Original Vision

> ok i will explain my idea so basically what we are building is a neuro
> symbolic architecture that emulates a super infants brain right? so it should
> already be able to take a book read it whether all at once or in chunks or
> whatever understand it make relations with past knowledge to create new nodes
> ideas thoughts etc. and to acquire this new knowledge and be able to use it
> when learning other new knowledge or performing tasks or making skills or
> understanding and building new logical process on the layer above the
> immutable hardcoded logical layer and by tools i mean tools that will let it
> acces the internet read and edit and write and create files on my device that
> is enough for now maybe also add a tool for accessing the terminal and alos a
> way for people to add ther own tools andthen we go back to the learning idea
> when it is presented with a book and it learns from it, it might not understand
> everything in the first round of studying so it should be able to access it
> again and re study it that is why the books that it is given will be stored in
> a seperate storage than the facts and skills and everything else this way it
> can recall it and learn new knowledge that it might get in reponse to the new
> knowledge it acquired elswhere thus creating a new knowldge node or idea or
> fact or skill it previously did not realize and also the first book it is give
> the first piece of knowledge it learns is what will dectate its ontology and
> core behavioral process going forward that is why i want to give it a book that
> will teach it isomorphism and to be a polymath so as to not impose any limits
> on its thinking etc. also its thinking and thoughts do not need to be in human
> language or emulate this wall of reasoning text that chatgpt does or claude
> does to emulate human logic that is a waste of tokens and resource and is fake
> we should have it reason and think in a way or laguage it is cpaable of and
> will result in the best results all while giving us access to its thoughts to
> see and understand so for exmaple 0 and 1 are the bits and building blocks of
> all computer language so what if it thinks in that and we can somehow translate
> that into human readable language or something

---

## 2. Architecture Response

I think the core direction is right: **neuro-symbolic, source-separated,
tool-grounded, with structured internal thought rather than generated reasoning
prose**. Three assumptions need changing before it becomes buildable.

### 2.1 The vision, translated honestly

“Super infant brain” is a useful metaphor, but the implementable version is a
**developmental cognitive loop**:

1. Perceive text, files, web pages, tool results.
2. Encode into concepts, claims, passages, and procedures.
3. Relate to existing knowledge.
4. Deliberate with symbolic inference plus neural similarity.
5. Act through tools.
6. Test itself.
7. Consolidate, revise, or forget.

A text-only system is really a **scholar**, not an infant. It has no
sensorimotor grounding. Tools give it eyes and hands: files, web, terminal. That
grounding matters because it turns symbols into consequences.

I would not rewrite the kernel to chase the metaphor. I would add cognitive
layers around the existing immutable rule floor.

### 2.2 What the current system can and cannot do

Current reality:

- The “brain” is a small forward-chaining S-P-O engine plus SQLite, LanceDB,
  NetworkX, and attention ranking.
- The Mouth is TinyChat15M with a **60-character context limit**
  (`interface/mouth.py:17`). It cannot read or understand a book.
- `full` mode writes inferred facts into the same store as source facts
  (`interface/core.py:27-39`), which is taint, not learning.
- There is no `source_graph.py`; the book-learning design exists only in
  `DESIGN.md:112-145`.
- Skills are currently **at most two-premise inference rules**
  (`learning/skill_compiler.py`). They cannot represent “read chapter → extract
  claim → test → revise.”
- There is no tool registry, no sandbox, no file/web/terminal access, and no
  upload path.
- Current data is polluted: 16 duplicate `bird can fly` facts, 5,401 vector rows
  with only 1,001 unique IDs, and zero skills.

Hardware matters here:

- i5-13420H, **7.6 GB RAM**, no GPU.
- A 3B/4B quantized local model is realistic. A 7B is tight and slow on CPU.
- A 15M model is a voice, not a reader.
- If extraction quality matters, an external model API is the practical option
  unless you accept slow overnight ingestion.

### 2.3 The architecture I would build

#### A. Five memory types, not one “memory”

| Memory | Contents |
|---|---|
| **Source library** | Books, web pages, files, exact passages, page offsets, hashes. Immutable. |
| **Working memory** | Current goal, retrieved passages, active hypotheses, current plan. |
| **Semantic memory** | Concepts, claims, ontology, relations, confidence, provenance. |
| **Episodic memory** | Study sessions, questions asked, failures, tool calls, outcomes. |
| **Procedural memory** | Skills, strategies, tool-use procedures. |

The source library is separate from facts and skills, exactly as you said. That
is what makes rereading and cross-book synthesis possible.

#### B. A machine-native thought trace

Do not make it think in raw binary. **Binary is a substrate, not a language of
thought.** Reasoning in bits would be unreadable and would not make it smarter.
The model's vectors are already numeric; the symbolic layer provides composition
and verification.

Use a typed internal representation instead:

- `PERCEIVE` — text, file, web page, tool result.
- `RECALL` — retrieve passages, concepts, claims.
- `LINK` — propose a relation.
- `ANALOGIZE` — map structure across domains.
- `INFER` — apply a rule.
- `HYPOTHESIZE` — create a candidate explanation.
- `TEST` — ask a question or run a tool.
- `PLAN` — choose a procedure.
- `ACT` — call a tool.
- `REFLECT` — evaluate confidence and failure.
- `CONSOLIDATE` — merge, dedupe, promote, deprecate.

Store each as a node in a thought DAG with inputs, outputs, confidence,
provenance, and timestamp. A renderer translates the trace into English on
demand. The trace is the truth; the English is a projection.

This gives you what you want: **no fake wall of reasoning text**, but full access
to how a conclusion was produced. Silent by default, inspectable when asked.

#### C. Book study loop

For each book:

1. **Survey** — parse TOC, headings, page structure, length.
2. **Chunk** — structural chunks first; fallback to ordered token windows with
   offsets.
3. **Extract** — entities, definitions, claims, questions, procedures. Every
   claim points to a passage.
4. **Link** — connect to known concepts; flag unknowns and contradictions.
5. **Self-test** — generate questions, answer from passages, mark gaps.
6. **Consolidate** — approve, reject, merge, or defer claims.
7. **Revisit** — reread passages when new knowledge creates a gap or
   contradiction.
8. **Synthesize** — create new concept/analogy/hypothesis nodes across books.

“Read it all at once” is not the goal. **Multiple passes with provenance** is.
For a whole book, use hierarchical outline plus retrieval; never dump the book
into a 60-character prompt.

Only reviewed claims become semantic facts. Candidate claims live in a review
queue. That is the firewall against book hallucination and test pollution.

#### D. Ontology: seed it, do not let the first book become a cage

A system that treats its first book as an absolute constitution is not limitless.
It becomes a single-book expert with a fixed bias.

Keep two layers separate:

- **Fixed meta-ontology** — Entity, Concept, Relation, Claim, Process, Question,
  Goal, Evidence, Tool, Skill.
- **Learned domain ontology** — concepts, aliases, predicate definitions,
  hierarchy, inverse relations.

GEB is an excellent seed for **ways of thinking**: isomorphism, recursion,
self-reference, levels, formal systems, strange loops. Represent those as
reusable strategies, not as the whole ontology. Let the domain ontology stay
revisable.

If GEB is the first full book, use selected chapters first. It is literary and
long; extraction will be noisy. A short logic/relations/isomorphism primer
followed by GEB is a better curriculum. The first book should teach **how to
learn**, not **what to believe**.

#### E. Procedures and the layer above the immutable rules

Keep the current layer model, but extend it:

- **L0** — immutable inference rules.
- **L1** — learned concepts and claims.
- **L2** — learned inference rules.
- **L3** — procedures and strategies.
- **L4** — meta-cognition: when to reread, ask, test, or use a tool.

Every learned item needs provenance, confidence, fitness, and a lifecycle:
candidate → tested → active → deprecated. Nothing learned can rewrite L0.

Current skill compilation is too narrow. Add procedures with:

- preconditions
- ordered steps
- tool calls
- expected effects
- success criteria
- rollback or disable path

Only generalize a procedure after three real traces share the same shape. That
is the Rule of Three, not speculation.

#### F. Tools as senses and hands

Tools are not just utilities. They are how the system grounds symbols.

Minimum registry:

- `library.ingest`
- `library.search`
- `knowledge.add_fact`
- `file.read`
- `file.write`
- `web.fetch`
- `terminal.run`

Each tool declares name, description, JSON input schema, permission level,
timeout, and handler. Load tools from a `tools/` directory so adding one does not
require editing core code.

Security model:

- File access restricted to a workspace root; canonicalize paths; reject
  traversal and symlinks.
- Web read-only first, domain allowlist, rate limits, cached results.
- Terminal allowlist, no `shell=True`, timeout, working-directory restriction,
  output cap.
- Read operations can be automatic. Write, network, and execute require
  approval.
- Audit every invocation.
- Tool results become observations with provenance, not automatic facts.

For third-party tools, use MCP or a manifest-based plugin API. Do not invent a
custom plugin runtime before you have three real tools.

### 2.4 Implementation phases

#### Phase 0 — Isolate and reset

- Archive `adam_memory.db`, `adam_vectors.lance`, `adam_save/`.
- Fix tests so SQLite and LanceDB always use temporary paths.
- Make the Flask app use an app factory instead of a global production core.
- Add dedupe and scoped `forget`/`reset`.
- Normalize the embedding model between `MemorySystem` and `SemanticIndex`.

Acceptance: test suite leaves production data byte-for-byte unchanged.

#### Phase 1 — Cognitive substrate

- Typed concept/claim/passage/thought tables.
- Thought DAG and renderer.
- Source library.
- Working-memory session object.
- No book learning yet.

Acceptance: store a passage, retrieve it with citation, and show a structured
trace.

#### Phase 2 — Book study MVP

- EPUB/TXT first; PDF and HTML next.
- Passage chunking with page offsets.
- Embedding index for passages, separate from facts.
- Candidate claims with approval/rejection.
- Self-test and reread loop.
- One chapter only as the first validation target.

Acceptance: ask a question, get an answer with exact citations, approve a claim,
and see it become a fact. Then add new knowledge and trigger a reread.

#### Phase 3 — Ontology and transfer

- Concept aliases, predicate definitions, hierarchy.
- GEB-derived strategies: isomorphism, recursion, self-reference.
- Structural analogy, not just matching identical predicates.
- Cross-book synthesis and contradiction handling.

Acceptance: connect two concepts from different chapters/books with a justified
analogy, and reject a bad one.

#### Phase 4 — Procedures and tools

- Procedure memory.
- Tool registry, sandbox, permissions, audit.
- File, web, terminal tools.
- Learned tool-use procedure from repeated traces.

Acceptance: one safe read-only tool, one write tool with approval, one procedure
compiled from three traces.

#### Phase 5 — Interface and evaluation

- Upload/library view.
- Passage and citation viewer.
- Claim review queue.
- Thought-trace viewer.
- Tool approval UI.
- Tests for citation, no-taint, reread improvement, and tool safety.

### 2.5 What I would not do

- Do not make it reason in raw binary.
- Do not let the first book define an immutable ontology.
- Do not auto-promote LLM-extracted claims.
- Do not start with all of GEB; test one chapter first.
- Do not use the 15M Mouth for extraction.
- Do not add a full plugin ecosystem before three tools exist.
- Do not call it “understanding” until it can cite, relate, apply, and
  self-correct.

### 2.6 Decisions requested

1. **Extraction model:** external API allowed, local 3B/4B only, or manual
   approval only?
2. **First curriculum:** curated logic/isomorphism primer then GEB, or GEB
   directly?
3. **Ontology:** fixed meta-ontology with revisable domain ontology — do you
   accept that, or do you want GEB to be the absolute first source?
4. **Tools:** read-only first, or file/write/terminal from the start with
   approval?
5. **MVP:** one EPUB/TXT book with citations and review, or try to build the full
   cognitive architecture in one pass?

My recommendation: Phase 0 + Phase 1 + one-chapter Phase 2 first. It proves the
architecture without pretending the current system can already learn from books.

---

## 3. User Decisions

> ok so what i need you to do is to add this and the prompt that i gave you taht
> led to you showing me this and asking these questions and my answers to them in
> a doc and cmmit and push it to github please
>
> 1. i want it small the entire thing should start at no more than 400mb of ram
> that is why i used the current model that i am using in the mouth also why do i
> need it bigger or better its entire job is only to talk to the user its the
> mouth it does not see or reason or think or anything it just takes the reasoning
> and thinking and results etc. and presents them to the user
>
> 2. what do you think is best ?
>
> 3. lets go with fixed meta-ontology with revisable domain ontology
>
> 4. file/write/terminal from the start with approval basically the tools that pi
> (https://pi.dev/) provides to its agents and llms
>
> 5. one EPUB/TXT/PDF/MD/HTML book or webpage etc.

---

## 4. Execution Plan Response

> I can’t create the document or commit/push while Plan Mode is active. Here is
> the exact execution plan.
>
> ### Answers to your five points
>
> **1. RAM and the Mouth — you are right.**  
> The 15M model is the Mouth. It only renders results; it does not read or reason.
> I was talking about a separate **Reader/Extractor** for books. Those are
> different roles.
>
> But there is a real budget problem: `docs/COMMITS.md` records ADAM core RSS at
> **~397 MB** after fastembed + LanceDB, plus **~62 MB** for `llama-server`. If
> 400 MB is the total cap, the current system is already at or over it. So:
>
> - Keep TinyChat15M as the Mouth.
> - Do not add a local 3B/4B Reader.
> - Use an external model API for extraction, or a deterministic/rule-based
>   Reader first.
> - Start implementation with a memory audit.
> - Likely replace or lazy-load the LanceDB/fastembed stack if 400 MB is a hard
>   total cap.
> - Define the budget precisely: total RSS of all ADAM processes, not just
>   Python.
>
> **2. Best first curriculum:** a short curated primer on logic, relations,
> recursion, and isomorphism, then GEB.  
> GEB is excellent for how to think, but it is long and literary. Use selected
> chapters first. The first book should teach **how to learn**, not become the
> permanent constitution.
>
> **3. Ontology:** fixed meta-ontology, revisable domain ontology.  
> GEB seeds strategies such as isomorphism, recursion, self-reference, levels,
> and strange loops. It does not define all predicates.
>
> **4. Tools:** Pi-style tools from the start, approval-gated.  
> Mirror the practical surface: read file, write/edit file, list/search files,
> run terminal commands, plus web fetch and library ingest/search. Use a
> workspace root, path validation, no `shell=True`, timeouts, and an audit log.
> User-added tools load from a manifest or MCP.
>
> **5. Input formats:** one source at a time.  
> Start with EPUB/TXT/MD/HTML, then PDF, then webpage URLs. Store exact passages
> separately from facts, claims, and skills.
>
> ### Document to create
>
> Path: `docs/design/neuro-symbolic-vision.md`
>
> Structure:
>
> ```markdown
> # ADAM Neuro-Symbolic Vision
>
> **Status:** Proposed
> **Date:** 2026-10-28
>
> ## Purpose
> Why this document exists and what decisions it records.
>
> ## Original Vision
> Verbatim user prompt describing:
> - neuro-symbolic infant-like learning
> - books as separate source memory
> - rereading and cross-book synthesis
> - GEB as first curriculum
> - machine-native thought instead of fake reasoning prose
> - binary as a possible internal representation
>
> ## Proposed Architecture
> Verbatim assistant response covering:
> - developmental cognitive loop
> - five memory types
> - typed thought trace
> - book study loop
> - meta-ontology vs domain ontology
> - procedures above immutable rules
> - tools as grounding
>
> ## Decisions
> 1. RAM target: <=400 MB total; Mouth stays TinyChat15M.
> 2. First curriculum: curated primer, then GEB.
> 3. Ontology: fixed meta-ontology, revisable domain ontology.
> 4. Tools: Pi-style file/write/terminal/web tools with approval.
> 5. Input: one EPUB/TXT/PDF/MD/HTML book or webpage at a time.
>
> ## Clarifications
> ### Mouth vs Reader
> The Mouth only renders. Book understanding needs a separate Reader/Extractor.
> ### Memory Budget
> Current documented core is ~397 MB; the 400 MB total cap needs an audit and likely
> replacement or lazy-loading of the embedding stack. No local 3B reader fits.
> ### First Book
> A primer teaches learning strategy; GEB tests and extends it.
> ### Tool Safety
> Read is automatic; write, network, and terminal require approval. All actions audited.
>
> ## Implementation Direction
> Phase 0: data isolation, memory audit, reset.
> Phase 1: thought trace, source library, typed graph.
> Phase 2: one-source ingestion, passages, citations, claim review.
> Phase 3: ontology, analogy, rereading, cross-source synthesis.
> Phase 4: procedures and Pi-style tools.
> Phase 5: UI, review queue, trace viewer, tool approvals.
>
> ## Open Questions
> - Is 400 MB total RSS or core only?
> - External extraction API allowed?
> - Which primer precedes GEB?
> - Which source format is the first validation target?
> ```
>
> ### Commit and push
>
> After writing the document:
>
> ```bash
> git status
> git diff --check
> git add docs/design/neuro-symbolic-vision.md
> git commit -m "docs: record neuro-symbolic vision and decisions"
> git push origin master
> git status
> ```
>
> No test run is needed for a documentation-only change. I will verify the
> working tree is clean and report the commit hash and push result.
>
> Approve this plan and switch out of Plan Mode, and I’ll create the document,
> commit it, and push it.

---

## 5. JEV Proposal

> ok i have an idea we can make a study mode that use the model or api for when
> it has books to study and read but instead of a api or local model we can use
> JEV what do you think or does it not work or mesh well also scrape the study
> mode idea what if we just have jev work in the background as well to supercharge
> everything how much ram are we looking at, at this point also i heard jev is a
> classification model will that cause problems ? also is it supervised or
> unsupervised and are there different version or alternatives to jev that
> emulate knn or clustering or random forest or descision tree

---

## 6. JEV Assessment

### 6.1 What JEV is

JEV is a hosted, proprietary **decision model** from TypeSafe AI. It is
discriminative, not generative. It does not write prose, summarize books, or
invent explanations. It takes:

- a `state` (context)
- one or more typed `questions`

and returns typed answers:

- **Choice** — pick one option from a supplied list.
- **Noul** — probability that a yes/no proposition is true.
- **Score** — a position or score over ordered levels.

Each answer comes with probabilities and a confidence value.

JEV is therefore not a Reader/Extractor in the sense ADAM needs. It is a
**background judge, router, tagger, and filter**. It can answer bounded
questions such as:

- “Is this passage a definition, a claim, an example, or irrelevant?”
- “Does this passage support this claim?”
- “Is this relation `is-a`, `part-of`, `causes`, or something else?”
- “Is this candidate fact novel, duplicate, contradictory, or unsafe to merge?”
- “Should this be handled by the Reader API, a human reviewer, or discarded?”
- “Which tool should handle this request?” — with a fixed tool list.

It cannot:

- generate a summary
- extract arbitrary S-P-O facts from free text
- invent a new ontology node
- write a procedure
- reason through a long proof
- replace a language model for open-ended study

**Conclusion:** JEV does not replace the Reader. It can reduce Reader calls and
make the system cheaper, faster, and more consistent at bounded decisions.

### 6.2 Does the classification limitation cause problems?

Yes, if it is used for the wrong job.

- **Good fit:** bounded labels, routing, scoring, filtering, verification,
  deduplication, contradiction checks, passage triage.
- **Bad fit:** generation, summarization, free-form extraction, open-ended
  reasoning, novel synthesis, ontology invention.

The risk is designing around a classifier and then expecting it to behave like a
reader. The safe pattern is:

1. Reader proposes candidates.
2. JEV filters, labels, scores, or verifies them.
3. Rules and provenance gate promotion.
4. Human reviews low-confidence cases.
5. Only approved claims enter semantic memory.

JEV should be an optional accelerator, not a hard dependency.

### 6.3 Is JEV supervised or unsupervised?

JEV is a **pretrained discriminative model**. It is not an unsupervised
clustering method. TypeSafe describes training with synthetic data and
“Reinforcement Learning for Calibrated Decisions” (RLCD); the architecture and
weights are not public. You do not train it on your labels. You define questions
and options at inference time and can supply a few examples in context.

In practical terms:

- **Zero-shot / few-shot** at the API boundary.
- Trained on synthetic data with RLCD; not trained on your labels.
- **Not kNN, not clustering, not a random forest, not a decision tree.**
- Neither a classical supervised classifier nor an unsupervised method: it is a
  pretrained discriminative decision model with proprietary weights.

### 6.4 RAM impact

| Option | Local RAM impact | Verdict for a 400 MB cap |
|---|---:|---|
| JEV hosted API | Negligible client memory | Fits; needs network, cost, privacy review |
| JEV + cache | Negligible | Fits; cache decisions by input hash |
| Laya open weights (~421M) | Hundreds of MB to ~1 GB depending runtime/quantization | Does not fit comfortably |
| Decider-2B | ~1.5–2.5 GB quantized | Does not fit |
| Kev-8B | ~4–6 GB quantized | Does not fit |
| scikit-learn TF-IDF + linear/kNN | ~50–100 MB | Fits, but needs labels/features |
| fastembed + kNN/clustering | Existing embedding stack already ~267 MB | Tight; must be measured and likely reduced |

If 400 MB is the **total** cap, JEV over HTTP is the only JEV-class option that
does not blow the budget. Local open-weight decision models do not fit. The
existing fastembed/LanceDB stack is already close to the ceiling; it needs a
memory audit before adding anything else.

### 6.5 Study mode: scrap the separate mode

If “scrape the study mode idea” means “scrap the separate mode,” that is the
better design.

Do not make study a separate chat mode. Make it a **pipeline** triggered by
ingestion:

1. Source is added.
2. Parser builds passages.
3. JEV triages passages and flags candidates.
4. Reader extracts claims from selected passages.
5. JEV verifies support, novelty, and contradictions.
6. Rules and review gate promotion.
7. Study session records gaps and schedules rereading.
8. New knowledge triggers re-evaluation of older passages.

JEV can run in the background in all modes for bounded decisions. The system
does not need a “study mode” button; it needs a study pipeline and a background
decision layer.

### 6.6 Alternatives and local options

**JEV-class hosted models**

- JEV (`jev-1.13` at the time of writing)
- Laya (open-weight sibling, ~421M parameters)
- Decider-2B (open weights)
- Kev-8B (open reproduction)

**Local zero-shot / few-shot classifiers**

- GLiClass — candidate labels at inference time
- SetFit — few-shot sentence-transformer classifier
- BART-MNLI / NLI-based zero-shot classification
- Fine-tuned ModernBERT or similar encoder

**Classical local models**

- k-nearest neighbors — instance-based; supervised labels or unsupervised
  retrieval depending on use
- KMeans / DBSCAN — unsupervised clustering
- Random Forest / Extra Trees — supervised ensembles
- Decision Tree — supervised, interpretable
- Logistic regression / linear SVM — supervised, cheap, strong baselines
- TF-IDF + linear model — very low RAM, good for narrow text classification

**Practical recommendation**

- Use JEV for bounded decisions only, behind a feature flag.
- Keep a deterministic fallback: rules, TF-IDF, or manual review.
- Do not put JEV in the critical path of book ingestion.
- Do not send private book text to a hosted API without explicit approval.
- Cache every decision by hash of state and questions.
- Pin the model version and record it in provenance.
- Evaluate JEV on ADAM's actual decisions before trusting it.

### 6.7 Background “supercharge” design

A safe background JEV layer would handle:

- passage triage
- claim support checks
- contradiction checks
- novelty and duplicate scoring
- importance scoring for review order
- tool routing from a fixed list
- memory consolidation decisions
- confidence-based escalation to Reader or human

It would not handle:

- generating facts
- writing summaries
- creating new concepts
- inventing procedures
- free-form reasoning

The controller remains responsible for the cognitive loop. JEV is a fast
“System One” advisor, not the mind.

### 6.8 Sources

- JEV overview and API primitives: <https://en.wikipedia.org/wiki/Jev_(AI_model)>
- LangChain JEV harness overview:
  <https://www.langchain.com/blog/building-a-harness-with-jev>
- Sebastian Raschka, “Language Models for Text Classification: From
  Bag-of-Words to JEV”:
  <https://magazine.sebastianraschka.com/p/classifier-history-and-jev>
- JEV vs classical ML benchmark: <https://mugenkyou.github.io/JEV-VS-ML/>
- JEV-class model comparison:
  <https://www.snowflake.com/en/developers/blog/choosing-the-right-jev-class-model-for-your-sql-pipeline/>
- JEV vs embeddings: <https://jevmodel.app/guides/jev-vs-embeddings>
- JEV network-traffic benchmark: <https://arxiv.org/html/2610.00376>
- JEV ecosystem analysis: <https://arxiv.org/abs/2609.30216>
- Pi agent harness: <https://pi.dev/>

---

## 7. Consolidated Decisions

1. **RAM cap:** target no more than 400 MB total. Measure total RSS of all ADAM
   processes. The current documented core is already ~397 MB, so Phase 0 must
   include a memory audit and likely a lighter embedding path.
2. **Mouth:** keep TinyChat15M. It is the voice, not the Reader.
3. **Reader:** no local 3B/4B model under the 400 MB cap. Use an external API or
   a deterministic/rule-based reader first.
4. **JEV:** optional background decision layer, not a Reader and not a hard
   dependency. Hosted API only if the RAM cap is strict.
5. **Ontology:** fixed meta-ontology; revisable domain ontology.
6. **First curriculum:** short logic/relations/isomorphism primer, then selected
   GEB chapters. GEB seeds strategies, not absolute truth.
7. **Tools:** Pi-style file read/write/edit, list/search, terminal, web, and
   library tools; approval-gated; workspace-rooted; audited.
8. **Input:** one EPUB/TXT/PDF/MD/HTML book or webpage at a time. Start with
   EPUB/TXT/MD/HTML; add PDF and webpage extraction next.
9. **Study:** not a separate chat mode. A pipeline triggered by ingestion, with
   background JEV triage and a review gate.
10. **Thought representation:** typed thought DAG, not raw binary and not
    generated reasoning prose. English is a rendered projection.

---

## 8. Open Questions

- Is 400 MB the total RSS of all ADAM processes, or only the Python core?
- Is a hosted JEV/Reader API acceptable for private book text?
- Which primer precedes GEB, and which GEB chapters are in the first pass?
- Which format is the first validation target: EPUB, TXT, or Markdown?
- Which tool permissions are automatic, and which require confirmation?
- Do we keep LanceDB/fastembed, or replace them with a lighter local path to meet
  the 400 MB cap?
- Should JEV be opt-in per workspace, or enabled globally with a local fallback?
