# The thought trace

**Status:** Current. Stage 4.6, Trace the Thought ([#35](https://github.com/AdamMostofi/ADAM/issues/35)).

Every chat turn records what ADAM did, as typed nodes. Any answer can then be checked: what was heard, what
was recalled, what was proved, and where the reply came from. The code is `memory/trace_log.py`, and
`ADAMCore.chat` builds the nodes.

## Data, not prose

A trace is a list of nodes. Every node has:
- a `type`;
- `inputs` and `outputs`;
- a `confidence`, which is `null` where a step is deterministic and no confidence applies;
- its `provenance`;
- a timestamp (`at`).

**English is rendered from the nodes on request** (`render()`, served at `/api/traces/<id>`). It is never
stored, so the explanation can't drift from what happened. The stored trace also doesn't hold the reply's text,
only its hash and length.

**The node types.** DT.1: start small, grow with use. `TRACE_VERSION` (1) says which vocabulary a trace uses.

| Type | Inputs | Outputs | Confidence | Provenance |
|---|---|---|---|---|
| `PERCEIVE` | the message | the route (small talk, question, statement, chatter), and the frustration reading and its cues | none | the user |
| `RECALL` | the query, the mode | the recalled facts (up to 20), whether the source library was searched, and the passages cited | none | the store, and the source library if searched |
| `INFER` | the mode, the inference budget | whether inference ran, how many conclusions were stored, and each proof the answer rests on: its steps, the given facts' origins, and its links to the store | the lowest confidence among the proved claims | the rules used |
| `ANSWER` | the route | `answer_source`, the reply's length and SHA-256, and its citations (source, offsets, hash) | none | the answer source |

**Linked to the evidence:**
- **A proof** names the stored fact's id and the ids of its Stage 1.4 derivation records (#30), via
  `MemorySystem.fact_link` and the new contract method `id_of`.
- **A citation** names the source, the passage's offsets and its hash, as in `/api/chat` (Stage 4.5).

A rendered trace for "Is Socrates mortal?":

1. Perceived "Is Socrates mortal?" as a question.
2. Recalled 5 facts from memory: socrates instance_of man; man subclass_of mortal; …
3. Inference stored 3 new conclusions this turn. Proved "socrates instance_of mortal" from 2 given facts by
   inheritance (fact #4, derivation record #2).
4. Answered from a proof.

**The recall line shows the kernel's own facts, such as "exists instance_of man".** Recall really returned them,
and a trace says what happened rather than tidying it.

## API

- **`POST /api/chat`** takes an optional `conversation` (1 to 64 letters, digits, `-` or `_`; anything else is
  ignored). It adds `trace_id` and `conversation` to the reply. Every earlier key is kept.
- **`GET /api/traces/<id>`** returns the trace's nodes, its conversation, turn number and version, and `text`,
  the rendered English, plus `packed`, which says whether its conversation is compressed (see Retention). It
  answers 404 for an unknown id.

## In the web chat

- **No status claims work that didn't happen.** The rotating labels ("Consulting the archives", "Testing
  propositions", …) changed every 1.4 s whatever the server was doing; they are gone. A chat request is one
  synchronous call, so the page can't know which step is running. While waiting, it says only "Working…".
- **Each answer has a "How this answer was reached" panel,** collapsed. It uses the existing `Reasoning`
  component, so there is no new panel. It loads the trace when first opened, and its lines go into the page
  as text.
- **The web chat names its conversation.** The id is kept in sessionStorage with the transcript. "New" starts
  a new conversation, and so does a new tab. Traces survive a reload, because the transcript keeps each turn's
  `trace_id`.
- **The frustration signal is read per conversation** (Stage 4.4), so "New" starts it afresh.

## Retention (the owner's call, 2026-11-27, revised the same day)

**Every trace is kept; old conversations are compressed, never deleted.** The first rule deleted conversations
beyond the last 5,000; the owner asked to compress them instead.
- **No limit on the turns in a conversation.**
- **The last 5,000 conversations are kept as they are.**
- **Older conversations are packed.** When a new conversation starts, each conversation beyond the 5,000 most
  recently active is packed into one zlib block.
- **What a conversation is.** One web chat, or one run of the CLI or of the web app for callers that don't
  name one.
- **The size, measured on 360 realistic turns:**
  - 1.75 KB a turn on disk as it is;
  - about 100 bytes a turn packed, 13 times smaller (lzma was barely better, at 13.5 times, and slower).
- **An old trace still opens by its id** (`"packed": true` in the response). Its id starts with 8 hex digits
  of its conversation's fingerprint, so it is found through its conversation without a per-trace index, which
  would eat most of the saving.
- **A packed conversation that resumes is unpacked first,** and carries on from its last turn.
- **The trade-off:** the file still grows, about 100 bytes per old turn, forever, and opening a packed trace
  unpacks its whole conversation (milliseconds).

Traces live in their own SQLite file beside the store, `adam_memory.traces.db`, because the engine store is
append-only and can't repack anything. The file is in the store guard, backups and reset.

## Also fixed: loading one save from several threads

`test_concurrent_save_and_load` failed once in a full run: "database disk image is malformed". It loads one
save from three threads at once. Since Stage 4.1, loading an engine save unpacks it into a folder, so two
loaders could write into the same folder.

The unpack is now atomic: it goes into a private folder, which is then renamed into place. A stress run of 25
rounds × 4 loaders passed. **The old code passed it too:** the race is rare and couldn't be reproduced on
demand, so the fix closes the window by construction, not by a reproduced failure.

## Limits

- **Four node types.** Tools, claims and learning have none yet (out of scope).
- **The trace says what happened, not why the routing chose it** beyond its route and cues.
- **Traces of the CLI and of the web app without a conversation id** are grouped by process run.
