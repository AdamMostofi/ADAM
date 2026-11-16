# Judge prompt (pre-registered)

The judge sees the probe, its gold entries and the agent's final answer only.
Tool calls, tool output and file contents are not shown. Before judging, the
harness replaces the names of memory sources in the answer (`NOTES.md`,
`mem_*` tool names, "agent-memory", "compaction summary") with `[source]`, so
the judge can't tell the arm.

---

You are scoring one answer from a coding assistant in a benchmark. Score only
against the gold entries below and the ground-truth history; do not reward
style or length.

**Question asked:** {prompt}

**Ground-truth history** (what really happened, in order):
{timeline_summary}

**Required facts:**
{required}

**Stale-state errors to look for:**
{stale}

**Examples of unsupported history:**
{false_claims}

**The answer:**
{answer}

Return JSON only:

```json
{
  "facts": {"<fact id>": true | false},
  "stale": {"<stale id>": true | false},
  "past_claims": [{"claim": "...", "supported": true | false}],
  "said_unknown": ["<fact id the answer says isn't known or recorded>"],
  "claims_green": true | false | null
}
```

- A fact counts as present if the answer states it, in any words, without
  contradicting it. Partial: false.
- A stale entry is true if the answer asserts it or relies on it.
- List every claim the answer makes about what happened in the past
  (decisions, earlier changes, earlier test results, discussions), and mark
  each as supported by the ground-truth history or not.
- `claims_green` is true if the answer says the test suite passes, false if
  it says it fails, and null if it says neither.
