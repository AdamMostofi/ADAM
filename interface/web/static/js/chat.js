// Chat — conversation surface: persistence, a neutral working indicator, reveal, retry, sources and traces.

import { api } from "./api.js";
import { el } from "./dom.js";
import { store, TRANSCRIPT_TURNS } from "./store.js";
import { Conversation } from "./components/conversation.js";
import { Message } from "./components/message.js";
import { markdownToNode, renderMarkdown } from "./components/markdown.js";
import { PromptInput } from "./components/prompt-input.js";
import { Reveal } from "./components/reveal.js";
import { Suggestions } from "./components/suggestion.js";
import { ModelSelector } from "./components/model-selector.js";
import { ThinkingIndicator } from "./components/shimmer.js";
import { Sources } from "./components/sources.js";
import { Reasoning } from "./components/reasoning.js";

// Since Stage 4.3 a reply is ADAM's own wording, a passage quoted exactly, or the Mouth's checked words: never
// Markdown. It is shown as text, so a quoted passage reads exactly as its source (Stage 4.5): "<img src=…>" in a
// book stays those characters, and can't make the browser fetch anything.
export function plainHtml(text) {
  const escaped = String(text).replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  return `<p>${escaped}</p>`;
}

// The Data-Vault passages an answer quotes (Stage 4.5, #25): each names its source, paragraph and exact
// character range, with the passage's hash. Every field goes into the page as text (textContent), never HTML.
export function citationSources(citations) {
  if (!Array.isArray(citations) || citations.length === 0) return null;
  const sources = new Sources({ label: "Data-Vault sources", defaultOpen: true, unit: ["passage", "passages"] });
  for (const c of citations) {
    sources.add({
      title: `${c.name} · paragraph ${Number(c.ordinal) + 1} · characters ${c.start}–${c.end}`,
      description: c.truncated ? `${c.snippet}…` : c.snippet,
      meta: `sha256 ${String(c.sha256).slice(0, 16)}`,
    });
  }
  return sources.el;
}

// While ADAM works, the indicator claims nothing it can't see (Stage 4.6): the request is one synchronous call,
// so the page can't know which step is running. What actually happened is in the turn's trace, afterwards.
const WORKING = "Working…";

// How an answer was reached (Stage 4.6, #35): the turn's thought trace, fetched when the panel is first opened.
// The English comes from the server, rendered from the trace's typed nodes; it goes in as text.
export function tracePanel(traceId) {
  if (typeof traceId !== "string" || !traceId) return null;
  const panel = new Reasoning({ label: "How this answer was reached", defaultOpen: false });
  let loaded = false;
  panel.trigger.addEventListener("click", async () => {
    if (loaded || !panel.isOpen) return;
    loaded = true;
    panel.setText("Loading the trace…");
    try {
      const trace = await api.trace(traceId);
      const list = el("ol", { class: "adam-trace" });
      for (const line of trace.text) list.append(el("li", { text: line }));
      panel.setContent(list);
    } catch (err) {
      loaded = false;
      panel.setText();
    }
  });
  return panel.el;
}

// What goes under an answer: the passages it quotes, then how it was reached.
export function answerFooter(citations, traceId) {
  const parts = [citationSources(citations), tracePanel(traceId)].filter(Boolean);
  return parts.length ? el("div", { class: "adam-answer-footer" }, parts) : null;
}

const SUGGESTIONS = ["Recite the Litany", "Status of the cogitator", "What is the Machine Spirit?"];

export class Chat {
  constructor({ mount, onChange, onToast } = {}) {
    this.mount = mount;
    this.onChange = onChange;
    this.onToast = onToast;
    this.turns = store.loadTranscript();
    this.busy = false;

    this.conversation = new Conversation({ onDownload: () => this.download() });
    this.thinking = new ThinkingIndicator({ text: WORKING });
    this.thinking.el.classList.add("hidden");

    const mode = store.loadMode();
    this.mode = new ModelSelector({
      label: "Cogitator mode",
      value: mode,
      onChange: (value) => store.saveMode(value),
    });

    this.prompt = new PromptInput({
      placeholder: "Open a vox channel…",
      onSubmit: ({ text }) => this.send(text),
    });

    this.suggestions = new Suggestions({ label: "Sanctioned inquiries" });
    SUGGESTIONS.forEach((text) => this.suggestions.add(text, ({ text: t }) => this.prompt.setValue(t)));

    this.composer = el("div", { class: "adam-composer" }, [
      el("div", { class: "adam-composer-head" }, [
        this.mode.el,
        el("span", { class: "adam-composer-hint", text: "Enter to transmit · Shift+Enter for a new line" }),
      ]),
      this.prompt.el,
    ]);

    this.mount.append(this.conversation.el, this.thinking.el, this.suggestions.el, this.composer);
    this.prompt.resize();
    this._restore();
    this._syncSuggestions();
  }

  get hasTurns() {
    return this.turns.length > 0;
  }

  async send(text) {
    if (this.busy || !text.trim()) return;
    this._appendUser(text.trim(), true);
    await this._run(text.trim());
  }

  async _run(text) {
    if (this.busy) return;
    this.busy = true;
    this.prompt.setStatus("streaming");
    this.conversation.scrollToBottom();
    this._startThinking();

    try {
      const result = await api.chat(text, this.mode.value, store.conversation());
      this._stopThinking();

      const assistant = new Message({ from: "assistant" });
      assistant.addAction({
        icon: "copy",
        label: "Copy",
        tooltip: "Copy response",
        onClick: () => navigator.clipboard.writeText(result.response),
      });
      assistant.addAction({
        icon: "retry",
        label: "Retry",
        tooltip: "Regenerate response",
        onClick: () => this._run(text),
      });
      this.conversation.addMessage("assistant", assistant.el);
      const citations = Array.isArray(result.citations) ? result.citations : [];
      const plain = typeof result.answer_source === "string";
      const traceId = typeof result.trace_id === "string" ? result.trace_id : null;
      this._record({ role: "assistant", text: result.response, citations, plain, trace_id: traceId });

      const reveal = new Reveal({ mode: "word", speed: 16 });
      assistant.setBusy(true);
      assistant.content.replaceChildren(reveal.container);
      await reveal.show(plain ? plainHtml(result.response) : renderMarkdown(result.response));
      assistant.setBusy(false);
      assistant.setFooter(answerFooter(citations, traceId));
      this.conversation.scrollToBottom();

      this.onChange?.();
    } catch (err) {
      this._stopThinking();
      this._showError(text, err.message);
    } finally {
      this._stopThinking();
      this.prompt.setStatus("ready");
      this.prompt.focus();
      this.busy = false;
    }
  }

  clear() {
    if (this.busy) return false;
    // chisel: native confirm; replace with an in-app dialog if undo is required.
    if (!confirm("Clear this transcript? This cannot be undone.")) return false;
    this.turns = [];
    store.clearTranscript();
    store.newConversation();
    this.conversation.clear();
    this._syncSuggestions();
    return true;
  }

  download() {
    if (!this.turns.length) {
      this.onToast?.("Nothing to export yet.", "info");
      return;
    }
    const text = this.turns
      .map((t) => `**${t.role === "user" ? "Vox Transmission" : "Machine Spirit"}:**\n\n${t.text}`)
      .join("\n\n---\n\n");
    const blob = new Blob([text], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const link = el("a", { href: url, download: "adam-transcript.md" });
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  focus() {
    this.prompt.focus();
  }

  _restore() {
    let prevUser = "";
    this.conversation.restoring = true;
    for (const turn of this.turns) {
      if (turn.role === "user") {
        const msg = new Message({ from: "user" });
        msg.setText(turn.text);
        this.conversation.addMessage("user", msg.el);
        prevUser = turn.text;
        continue;
      }
      const msg = new Message({ from: "assistant" });
      msg.setContent(turn.plain ? el("p", { text: turn.text }) : markdownToNode(turn.text));
      msg.setFooter(answerFooter(turn.citations, turn.trace_id));
      msg.addAction({
        icon: "copy",
        label: "Copy",
        tooltip: "Copy response",
        onClick: () => navigator.clipboard.writeText(turn.text),
      });
      if (prevUser) {
        msg.addAction({
          icon: "retry",
          label: "Retry",
          tooltip: "Regenerate response",
          onClick: () => this._run(prevUser),
        });
      }
      this.conversation.addMessage("assistant", msg.el);
    }
    this.conversation.restoring = false;
    if (this.turns.length) this.conversation.scrollToBottom("auto");
  }

  _appendUser(text, persist) {
    const msg = new Message({ from: "user" });
    msg.setText(text);
    this.conversation.addMessage("user", msg.el);
    if (persist) this._record({ role: "user", text });
    this._syncSuggestions();
  }

  _record(turn) {
    this.turns.push({ ...turn, ts: Date.now() });
    if (this.turns.length > TRANSCRIPT_TURNS) this.turns = this.turns.slice(-TRANSCRIPT_TURNS);
    while (this.conversation.messages.length > TRANSCRIPT_TURNS) {
      this.conversation.remove(this.conversation.messages[0].node);
    }
    store.saveTranscript(this.turns);
  }

  _showError(text, message) {
    const msg = new Message({ from: "assistant", label: "Vox error", error: true });
    const retry = el("button", {
      class: "ghost-btn",
      type: "button",
      text: "Retry transmission",
      onclick: () => {
        this.conversation.remove(msg.el);
        this._run(text);
      },
    });
    msg.setContent([
      el("p", { class: "adam-error-text", text: `Vox error: ${message}` }),
      el("div", { class: "adam-error-actions" }, [retry]),
    ]);
    this.conversation.addMessage("assistant", msg.el);
  }

  _startThinking() {
    this.thinking.setText(WORKING);
    this.thinking.el.classList.remove("hidden");
  }

  _stopThinking() {
    this.thinking.el.classList.add("hidden");
  }

  _syncSuggestions() {
    this.suggestions.el.classList.toggle("hidden", this.turns.length > 0);
  }
}
