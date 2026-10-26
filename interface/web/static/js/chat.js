// Chat — conversation surface: persistence, thinking phases, reveal, retry.

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

const PHASES = [
  "Consulting the archives",
  "Cross-checking the vaults",
  "Testing propositions",
  "Forming the response",
];

const SUGGESTIONS = ["Recite the Litany", "Status of the cogitator", "What is the Machine Spirit?"];

export class Chat {
  constructor({ mount, onChange, onToast } = {}) {
    this.mount = mount;
    this.onChange = onChange;
    this.onToast = onToast;
    this.turns = store.loadTranscript();
    this.busy = false;
    this._phaseTimer = null;

    this.conversation = new Conversation({ onDownload: () => this.download() });
    this.thinking = new ThinkingIndicator({ text: PHASES[0] });
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
    this.prompt.focus();
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
      const result = await api.chat(text, this.mode.value);
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
      this._record({ role: "assistant", text: result.response });

      const reveal = new Reveal({ mode: "word", speed: 16 });
      assistant.setBusy(true);
      assistant.content.replaceChildren(reveal.container);
      await reveal.show(renderMarkdown(result.response));
      assistant.setBusy(false);
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
      msg.setContent(markdownToNode(turn.text));
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
    this._stopThinking();
    let i = 0;
    this.thinking.setText(PHASES[0]);
    this.thinking.el.classList.remove("hidden");
    this._phaseTimer = setInterval(() => {
      i = (i + 1) % PHASES.length;
      this.thinking.setText(PHASES[i]);
    }, 1400);
  }

  _stopThinking() {
    if (this._phaseTimer) clearInterval(this._phaseTimer);
    this._phaseTimer = null;
    this.thinking.el.classList.add("hidden");
  }

  _syncSuggestions() {
    this.suggestions.el.classList.toggle("hidden", this.turns.length > 0);
  }
}
