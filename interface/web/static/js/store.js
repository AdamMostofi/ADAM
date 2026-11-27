// ADAM — transcript + preference persistence.

const TRANSCRIPT_KEY = "adam-transcript-v1";
const MODE_KEY = "adam-mode";
export const TRANSCRIPT_TURNS = 50;
const MAX_BYTES = 180_000;

function cleanTurn(turn) {
  if (!turn || typeof turn !== "object") return null;
  const role = turn.role === "user" || turn.role === "assistant" ? turn.role : null;
  const text = typeof turn.text === "string" ? turn.text : "";
  if (!role || !text.trim()) return null;
  const clean = { role, text, ts: Number(turn.ts) || Date.now() };
  if (turn.plain === true) clean.plain = true;   // shown as text, not Markdown (Stage 4.5)
  if (typeof turn.trace_id === "string" && /^[0-9a-f]{1,64}$/.test(turn.trace_id)) clean.trace_id = turn.trace_id;
  const citations = cleanCitations(turn.citations);
  if (citations.length) clean.citations = citations;
  return clean;
}

// Citations kept with a turn (Stage 4.5): only the known fields, with their expected types.
function cleanCitations(list) {
  if (!Array.isArray(list)) return [];
  return list
    .filter((c) => c && typeof c === "object" && typeof c.name === "string" && typeof c.snippet === "string")
    .map((c) => ({
      source: String(c.source ?? ""),
      name: c.name,
      ordinal: Number(c.ordinal) || 0,
      start: Number(c.start) || 0,
      end: Number(c.end) || 0,
      sha256: String(c.sha256 ?? ""),
      snippet: c.snippet,
      truncated: Boolean(c.truncated),
    }));
}

function trim(turns) {
  const kept = turns.slice(-TRANSCRIPT_TURNS);
  while (kept.length > 1 && new TextEncoder().encode(JSON.stringify(kept)).length > MAX_BYTES) kept.shift();
  return kept;
}

const CONVERSATION_KEY = "adam-conversation";

function freshConversationId() {
  const hex = (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`).replace(/[^0-9a-f-]/gi, "");
  return `web-${hex}`.slice(0, 64);
}

export const store = {
  // The conversation this transcript belongs to (Stage 4.6): ADAM files each turn's thought trace under it.
  // "New" starts another; a new browser tab is another too.
  conversation() {
    try {
      let id = sessionStorage.getItem(CONVERSATION_KEY);
      if (!id || !/^[A-Za-z0-9_-]{1,64}$/.test(id)) {
        id = freshConversationId();
        sessionStorage.setItem(CONVERSATION_KEY, id);
      }
      return id;
    } catch {
      this._conversation ??= freshConversationId();
      return this._conversation;
    }
  },

  newConversation() {
    const id = freshConversationId();
    this._conversation = id;
    try {
      sessionStorage.setItem(CONVERSATION_KEY, id);
    } catch {
      /* storage unavailable — the id stays in memory */
    }
    return id;
  },

  loadTranscript() {
    try {
      const raw = sessionStorage.getItem(TRANSCRIPT_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return trim(parsed.map(cleanTurn).filter(Boolean));
    } catch {
      return [];
    }
  },

  saveTranscript(turns) {
    try {
      sessionStorage.setItem(TRANSCRIPT_KEY, JSON.stringify(trim(turns)));
    } catch {
      /* storage unavailable — transcript stays in memory */
    }
  },

  clearTranscript() {
    try { sessionStorage.removeItem(TRANSCRIPT_KEY); } catch { /* ignore */ }
  },

  loadMode() {
    try {
      const mode = localStorage.getItem(MODE_KEY);
      return mode === "simple" ? "simple" : "full";
    } catch {
      return "full";
    }
  },

  saveMode(mode) {
    try { localStorage.setItem(MODE_KEY, mode); } catch { /* ignore */ }
  },
};
