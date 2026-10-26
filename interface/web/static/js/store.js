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
  return { role, text, ts: Number(turn.ts) || Date.now() };
}

function trim(turns) {
  const kept = turns.slice(-TRANSCRIPT_TURNS);
  while (kept.length > 1 && new TextEncoder().encode(JSON.stringify(kept)).length > MAX_BYTES) kept.shift();
  return kept;
}

export const store = {
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
